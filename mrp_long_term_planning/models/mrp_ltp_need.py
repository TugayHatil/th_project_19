# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MO_OPEN_STATES = ("draft", "confirmed", "progress", "to_close")
WO_CLOSED_STATES = ("done", "cancel")


class MrpLtpNeedSchedule(models.Model):
    """Planner-confirmed production window for one product/month need.

    Only the confirmed decision is persisted; the system suggestion is
    recomputed on every load from demand, calendar and load data, so it
    never goes stale. A confirmed window reserves capacity on every
    workcenter the need touches before unconfirmed needs are placed.
    """

    _name = "mrp.ltp.need.schedule"
    _description = "Need-Level Planned Production Window"
    _order = "period, product_id"

    product_id = fields.Many2one(
        "product.product", string="Product", required=True, index=True,
        ondelete="cascade",
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Warehouse", index=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company,
    )
    year = fields.Integer(required=True)
    month = fields.Integer(required=True)
    # YYYYMM — monotonic key like mrp.ltp.line.
    period = fields.Integer(compute="_compute_period", store=True, index=True)
    planned_start = fields.Date(required=True)
    planned_end = fields.Date(required=True)
    # snapshot of the need quantity at confirm time — informational only;
    # capacity reservation always uses the live quantity
    need_qty = fields.Float(
        string="Need Quantity", digits="Long-Term Planning Quantity",
        default=0.0,
    )

    @api.depends("year", "month")
    def _compute_period(self):
        for line in self:
            line.period = line.year * 100 + line.month

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mrp_ltp_need_sched_uniq
            ON mrp_ltp_need_schedule
               (company_id, product_id, COALESCE(warehouse_id, 0), period)
        """)


class MrpLtpNeed(models.AbstractModel):
    """Read-only bridge between the capacity grid and need lines.

    Each row is one unmet production demand (product x month, the IM of
    the planning grid). The engine backward-schedules it through the
    product's BoM operations into daily workcenter capacity — earliest
    deadline first — and reports the suggested window plus an overload
    flag when capacity cannot fit it before the month end. Planners may
    override the window; confirmed windows consume capacity ahead of the
    suggestion pass. Nothing is rescheduled automatically.
    """

    _name = "mrp.ltp.need"
    _description = "Need-Level Capacity Planning Service"

    # ------------------------------------------------------------------
    # RPC service layer
    # ------------------------------------------------------------------

    @api.model
    def get_need_filters(self):
        Line = self.env["mrp.ltp.line"]
        periods = Line._periods(*Line._current_period())
        return {
            "periods": Line._period_payload(periods),
            "workcenters": self.env["mrp.workcenter"].search_read(
                [("company_id", "in", self.env.companies.ids)],
                ["name"], order="name"),
        }

    @api.model
    def get_need_grid(self, workcenter_ids=False, query="",
                      overload_only=False, start_year=False,
                      start_month=False, offset=0, limit=80):
        """One page of need rows, EDD-ordered.

        The full suggestion engine runs on every call — the plan must
        reflect the latest orders, workorders and confirmed windows.
        Filtering/paging stays server-side like the other grids.
        """
        Line = self.env["mrp.ltp.line"]
        if start_year and start_month:
            sy, sm = int(start_year), int(start_month)
        else:
            sy, sm = Line._current_period()
        periods = Line._periods(sy, sm)
        rows = self._need_rows(
            periods, workcenter_ids=workcenter_ids,
            query=query or "", overload_only=bool(overload_only))
        offset, limit = int(offset or 0), int(limit or 80)
        return {
            "periods": Line._period_payload(periods),
            "total": len(rows),
            "rows": rows[offset:offset + limit],
        }

    @api.model
    def set_need_schedule(self, product_id, year, month,
                          planned_start, planned_end, warehouse_id=False):
        """Confirm (or move) the production window of one need line."""
        product_id = int(product_id)
        year, month = int(year), int(month)
        try:
            start = fields.Date.from_string(planned_start)
            end = fields.Date.from_string(planned_end)
        except Exception as exc:
            raise UserError(_("Invalid date format.")) from exc
        if not start or not end or end < start:
            raise UserError(_(
                "Planned end must not be earlier than planned start."))
        Schedule = self.env["mrp.ltp.need.schedule"]
        rec = Schedule.search([
            ("product_id", "=", product_id),
            ("warehouse_id", "=", warehouse_id or False),
            ("year", "=", year),
            ("month", "=", month),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        qty = self._live_need_qty(product_id, year, month)
        vals = {
            "planned_start": start,
            "planned_end": end,
            "need_qty": qty,
        }
        if rec:
            rec.write(vals)
        else:
            vals.update({
                "product_id": product_id,
                "warehouse_id": warehouse_id or False,
                "year": year,
                "month": month,
            })
            Schedule.create(vals)
        return {"ok": True}

    @api.model
    def clear_need_schedule(self, product_id, year, month,
                            warehouse_id=False):
        """Drop the confirmed window — the need returns to suggestion."""
        self.env["mrp.ltp.need.schedule"].search([
            ("product_id", "=", int(product_id)),
            ("warehouse_id", "=", warehouse_id or False),
            ("year", "=", int(year)),
            ("month", "=", int(month)),
            ("company_id", "=", self.env.company.id),
        ]).unlink()
        return {"ok": True}

    @api.model
    def _live_need_qty(self, product_id, year, month):
        """Current unmet demand of one product/month — the quantity a
        confirmed window still reserves, even if it has drifted since
        confirm time."""
        Line = self.env["mrp.ltp.line"]
        abs_month = Line._abs_month(year, month)
        periods = Line._periods(*Line._current_period())
        req = self.env["mrp.ltp.capacity"]._required_qty_map(periods)
        return req.get((product_id, abs_month), 0.0)

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------

    @api.model
    def _need_rows(self, periods, workcenter_ids=False, query="",
                   overload_only=False):
        Line = self.env["mrp.ltp.line"]
        Cap = self.env["mrp.ltp.capacity"]
        today = fields.Date.context_today(self)

        # unmet production demand per (product, month)
        req_map = Cap._required_qty_map(periods)
        if not req_map:
            return []
        first_idx = Line._abs_month(*periods[0])
        last_idx = Line._abs_month(*periods[-1])

        needs = []
        product_ids = set()
        for (pid, abs_month), qty in req_map.items():
            if qty <= 0 or not (first_idx <= abs_month <= last_idx):
                continue
            product_ids.add(pid)
            # deadline: the last local day of the demand month — output
            # must exist inside its own period to count as on time
            nxt = abs_month + 1
            deadline = (datetime(nxt // 12, nxt % 12 + 1, 1)
                        - timedelta(days=1)).date()
            needs.append({"pid": pid, "abs_month": abs_month,
                          "qty": qty, "deadline": deadline})

        products = self.env["product.product"].browse(product_ids)
        prod_map = {p.id: p for p in products}
        boms = self.env["mrp.bom"]._bom_find(products)
        bom_by_pid = {
            getattr(k, "id", k): b for k, b in boms.items()}

        # per-need operation chain [(wc_id, hours_per_unit)], in BoM order
        wc_ids = set()
        for need in needs:
            bom = bom_by_pid.get(need["pid"])
            ops = []
            if bom and bom.type == "normal":
                ops = [
                    (op.workcenter_id.id,
                     (op.time_cycle or 0.0) / 60.0
                     / (bom.product_qty or 1.0))
                    for op in bom.operation_ids
                    if op.workcenter_id and op.time_cycle
                ]
            need["ops"] = ops
            wc_ids.update(wc for wc, _h in ops)

        # confirmed planner windows reserve capacity ahead of suggestions
        period_min = periods[0][0] * 100 + periods[0][1]
        period_max = periods[-1][0] * 100 + periods[-1][1]
        schedules = {}
        for s in self.env["mrp.ltp.need.schedule"].search_read([
                ("period", ">=", period_min),
                ("period", "<=", period_max),
                ("company_id", "=", self.env.company.id),
            ], ["product_id", "year", "month",
                "planned_start", "planned_end", "need_qty",
                "warehouse_id"]):
            s["start_d"] = fields.Date.to_date(s["planned_start"])
            s["end_d"] = fields.Date.to_date(s["planned_end"])
            schedules[(s["product_id"][0],
                       Line._abs_month(s["year"], s["month"]))] = s

        wcs = self.env["mrp.workcenter"].browse(sorted(wc_ids))
        cap_map, plan_map = self._daily_load_maps(wcs, periods)
        wc_name = {wc.id: wc.name for wc in wcs}

        # allocated load: confirmed windows + suggestion placements.
        # A confirmed window reserves each workcenter's op-hours spread
        # over the window's own working days (proportional to capacity)
        alloc = defaultdict(float)
        for need in needs:
            key = (need["pid"], need["abs_month"])
            sch = schedules.get(key)
            if not sch or not need["ops"]:
                continue
            days = self._work_days(
                sch["start_d"], sch["end_d"], need["ops"], cap_map)
            wc_tot = defaultdict(float)
            for (wc_id, _day), hours in days.items():
                wc_tot[wc_id] += hours
            op_hours = defaultdict(float)
            for wc_id, per_unit in need["ops"]:
                op_hours[wc_id] += per_unit * need["qty"]
            for (wc_id, day), hours in days.items():
                if wc_tot[wc_id] > 0:
                    alloc[(wc_id, day)] += (
                        op_hours[wc_id] * hours / wc_tot[wc_id])

        # EDD placement for unconfirmed needs
        for need in sorted(needs, key=lambda n: (n["deadline"], n["pid"])):
            key = (need["pid"], need["abs_month"])
            if key in schedules:
                continue
            self._place_backward(need, cap_map, plan_map, alloc, today)

        rows = []
        q = (query or "").strip().lower()
        wc_filter = set(int(i) for i in workcenter_ids) \
            if workcenter_ids else set()
        for need in sorted(needs, key=lambda n: (n["deadline"], n["pid"])):
            row = self._row_payload(
                need, prod_map[need["pid"]], schedules, wc_name, today)
            if q and q not in (row["name"] or "").lower() \
                    and q not in (row["code"] or "").lower():
                continue
            if wc_filter and not (wc_filter & set(row["wc_ids"])):
                continue
            if overload_only and not row["overload"]:
                continue
            rows.append(row)
        return rows

    @api.model
    def _place_backward(self, need, cap_map, plan_map, alloc, today):
        """Backward-schedule one need's ops through free daily capacity.

        Ops run in reverse BoM order; each op ends where the next begins.
        What does not fit before today spills forward past the deadline —
        the row then flags overload. A bounded horizon keeps workcenters
        with zero capacity from looping forever.
        """
        horizon = today + timedelta(days=730)
        cursor = need["deadline"]
        placed_start = None
        placed_end = None
        unplaced = False
        for wc_id, per_unit in reversed(need["ops"]):
            remaining = need["qty"] * per_unit
            if remaining <= 0:
                continue
            day = cursor
            # backward: consume free capacity while the day is plannable
            while remaining > 1e-9 and day >= today:
                free = (cap_map.get(wc_id, {}).get(day, 0.0)
                        - plan_map.get(wc_id, {}).get(day, 0.0)
                        - alloc[(wc_id, day)])
                if free > 1e-9:
                    take = min(free, remaining)
                    alloc[(wc_id, day)] += take
                    remaining -= take
                    placed_start = day
                    if placed_end is None:
                        placed_end = day
                day -= timedelta(days=1)
            # forward: leftover could not be produced in time — it lands
            # after the deadline and the row flags overload
            while remaining > 1e-9:
                day += timedelta(days=1)
                if day > horizon:
                    unplaced = True
                    break
                free = (cap_map.get(wc_id, {}).get(day, 0.0)
                        - plan_map.get(wc_id, {}).get(day, 0.0)
                        - alloc[(wc_id, day)])
                if free > 1e-9:
                    take = min(free, remaining)
                    alloc[(wc_id, day)] += take
                    remaining -= take
                    placed_end = day
            if placed_start:
                cursor = placed_start
            elif not unplaced and day > cursor:
                cursor = day
        need["sug_start"] = placed_start
        need["sug_end"] = placed_end
        need["unplaced"] = unplaced

    @api.model
    def _row_payload(self, need, product, schedules, wc_name, today):
        key = (need["pid"], need["abs_month"])
        sch = schedules.get(key)
        wc_ids = [wc for wc, _h in need["ops"]]
        req_hours = need["qty"] * sum(h for _w, h in need["ops"])
        if not need["ops"]:
            # no BoM operations — capacity cannot be attributed; this is
            # a data problem, not an overload
            status, start, end, overload = "missing", None, None, False
        elif sch:
            start, end = sch["start_d"], sch["end_d"]
            overload = end > need["deadline"] or start < today
            status = "planned_late" if overload else "planned"
        else:
            start = need.get("sug_start")
            end = need.get("sug_end")
            overload = need.get("unplaced") or start is None \
                or end > need["deadline"] or start < today
            status = "late" if overload else "ok"
        wc_names = [wc_name[wc] for wc in dict.fromkeys(wc_ids)
                    if wc in wc_name]
        return {
            "product_id": need["pid"],
            "name": product.display_name,
            "code": product.default_code or "",
            "uom": product.uom_id.name,
            "year": need["deadline"].year,
            "month": need["deadline"].month,
            "period": "%d-%02d" % (
                need["deadline"].year, need["deadline"].month),
            "deadline": fields.Date.to_string(need["deadline"]),
            "qty": need["qty"],
            "wc_ids": wc_ids,
            "workcenters": ", ".join(wc_names),
            "req_hours": req_hours,
            "start": fields.Date.to_string(start) if start else False,
            "end": fields.Date.to_string(end) if end else False,
            "overload": overload,
            "status": status,
            "planned": bool(sch),
        }

    # ------------------------------------------------------------------
    # Daily capacity / load maps
    # ------------------------------------------------------------------

    @api.model
    def _daily_load_maps(self, workcenters, periods):
        """({wc: {date: cap_hours}}, {wc: {date: plan_hours}}).

        Same inputs as the monthly grid — calendar hours x parallel
        capacity x time efficiency x monthly factor, and open workorder
        duration_expected — but bucketed per local day so needs can be
        placed day-accurately."""
        Cap = self.env["mrp.ltp.capacity"]
        Line = self.env["mrp.ltp.line"]
        tz = Cap._tz()
        first = Cap._month_bounds(*periods[0])[0]
        nxt = Line._abs_month(*periods[-1]) + 1
        last = Cap._month_bounds(nxt // 12, nxt % 12 + 1)[0]
        factor_map = Cap._factor_map(workcenters, periods)

        cap_map = {}
        for wc in workcenters:
            parallel = 1.0
            for cap_line in wc.capacity_ids:
                if not cap_line.product_id:
                    parallel = cap_line.capacity or 1.0
                    break
            eff = parallel * (wc.time_efficiency or 100.0) / 100.0
            day_cap = defaultdict(float)
            for iv_s, iv_e in Cap._work_intervals(wc, first, last):
                for day, seconds in self._split_days(tz, iv_s, iv_e).items():
                    month_idx = day.year * 12 + day.month - 1
                    factor = factor_map.get((wc.id, month_idx), 1.0)
                    day_cap[day] += seconds / 3600.0 * eff * factor
            cap_map[wc.id] = day_cap

        plan_map = {wc.id: defaultdict(float) for wc in workcenters}
        wos = self.env["mrp.workorder"].search_read([
            ("workcenter_id", "in", workcenters.ids),
            ("state", "not in", list(WO_CLOSED_STATES)),
            ("production_id.state", "in", list(MO_OPEN_STATES)),
        ], ["workcenter_id", "date_start", "date_finished",
            "duration_expected"])
        wc_by_id = {wc.id: wc for wc in workcenters}
        for wo in wos:
            wc = wc_by_id.get(wo["workcenter_id"][0])
            hours = (wo["duration_expected"] or 0.0) / 60.0
            if not wc or not hours:
                continue
            start = (pytz.UTC.localize(wo["date_start"])
                     if wo["date_start"] else None)
            end = (pytz.UTC.localize(wo["date_finished"])
                   if wo["date_finished"] else None)
            day_seconds = defaultdict(float)
            if start and end and end > start:
                for iv_s, iv_e in Cap._work_intervals(wc, start, end):
                    for day, secs in self._split_days(tz, iv_s, iv_e).items():
                        day_seconds[day] += secs
            total = sum(day_seconds.values())
            if total > 0:
                for day, secs in day_seconds.items():
                    plan_map[wc.id][day] += hours * secs / total
            else:
                anchor = start.astimezone(tz).date() if start \
                    else first.astimezone(tz).date()
                plan_map[wc.id][anchor] += hours
        return cap_map, plan_map

    @staticmethod
    def _split_days(tz, start, end):
        """{local_date: seconds} — one working interval split across the
        local calendar days it overlaps."""
        out = defaultdict(float)
        cursor = start.astimezone(tz)
        stop = end.astimezone(tz)
        while cursor < stop:
            nxt_midnight = (cursor + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            seg_end = min(nxt_midnight, stop)
            out[cursor.date()] += (seg_end - cursor).total_seconds()
            cursor = seg_end
        return out

    @api.model
    def _work_days(self, start, end, ops, cap_map):
        """{(wc_id, date): working hours} inside a confirmed window,
        per involved workcenter — used to spread the reserved load."""
        out = {}
        if not start or not end:
            return out
        day = start
        while day <= end:
            for wc_id, _h in ops:
                hours = cap_map.get(wc_id, {}).get(day, 0.0)
                if hours > 0:
                    out[(wc_id, day)] = hours
            day += timedelta(days=1)
        return out
