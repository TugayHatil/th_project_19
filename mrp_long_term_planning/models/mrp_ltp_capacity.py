# -*- coding: utf-8 -*-
from datetime import datetime

import pytz

from odoo import _, api, models
from odoo.exceptions import UserError

# Work orders / productions that still represent future workload.
MO_OPEN_STATES = ("draft", "confirmed", "progress", "to_close")
WO_CLOSED_STATES = ("done", "cancel")


class MrpLtpCapacity(models.AbstractModel):
    """Read-only capacity service for the 12-month workcenter grid.

    Nothing is persisted here: capacity comes from the workcenter's working
    calendar and workload from planned mrp.workorder records — the screen is
    analysis-only and never reschedules anything (BRD §18-20).
    """

    _name = "mrp.ltp.capacity"
    _description = "Long-Term Capacity Planning Service"

    # ------------------------------------------------------------------
    # RPC service layer
    # ------------------------------------------------------------------

    @api.model
    def get_capacity_filters(self):
        Line = self.env["mrp.ltp.line"]
        periods = Line._periods(*Line._current_period())
        return {
            "periods": Line._period_payload(periods),
            "workcenters": self.env["mrp.workcenter"].search_read(
                [("company_id", "in", self.env.companies.ids)],
                ["name"], order="name"),
        }

    @api.model
    def get_capacity_grid(self, workcenter_ids=False, query="",
                          overload_only=False, start_year=False,
                          start_month=False):
        """All visible workcenters x 12 periods. Workcenters are few (tens),
        so the whole set is returned — filtering stays server-side and the
        frontend only renders.

        Per month / per workcenter (BRD §7-12):
            cap  = calendar capacity hours
            plan = planned production (open workorders)
            rem  = cap - plan
            req  = required production (unmet demand routed through BOM ops)
            tot  = plan + req
            diff = cap - tot
        """
        Line = self.env["mrp.ltp.line"]
        if start_year and start_month:
            sy, sm = int(start_year), int(start_month)
        else:
            sy, sm = Line._current_period()
        periods = Line._periods(sy, sm)

        domain = [("company_id", "in", self.env.companies.ids)]
        if workcenter_ids:
            domain.append(("id", "in", [int(i) for i in workcenter_ids]))
        if query and query.strip():
            domain.append(("name", "ilike", query.strip()))
        workcenters = self.env["mrp.workcenter"].search(
            domain, order="name, id")

        cap_map = self._capacity_map(workcenters, periods)
        plan_map = self._workload_map(workcenters, periods)
        req_map = self._required_load_map(periods, workcenters)
        factor_map = self._factor_map(workcenters, periods)

        rows = [
            self._build_row(wc, periods, cap_map, plan_map, req_map,
                            factor_map)
            for wc in workcenters
        ]
        if overload_only:
            rows = [row for row in rows if row["overload"]]
        return {
            "periods": Line._period_payload(periods),
            "rows": rows,
        }

    def _build_row(self, wc, periods, cap_map, plan_map, req_map,
                   factor_map):
        """One grid row: standard calendar capacity scaled by the monthly
        factor (BRD §5) — every downstream metric derives from the revised
        capacity."""
        Line = self.env["mrp.ltp.line"]
        calendar = wc.resource_calendar_id
        hours_per_day = (calendar.hours_per_day or 8.0) if calendar else 8.0
        cells = []
        overloaded = False
        for year, month in periods:
            key = (wc.id, Line._abs_month(year, month))
            factor = factor_map.get(key, 1.0)
            cap_h = cap_map.get(key, 0.0) * factor
            plan_h = plan_map.get(key, 0.0)
            req_h = req_map.get(key, 0.0)
            rem_h = cap_h - plan_h
            tot_h = plan_h + req_h
            diff_h = cap_h - tot_h
            if diff_h < -1e-6:
                overloaded = True
            cells.append({
                "year": year, "month": month, "factor": factor,
                "cap_h": cap_h, "cap_d": cap_h / hours_per_day,
                "plan_h": plan_h, "plan_d": plan_h / hours_per_day,
                "rem_h": rem_h, "rem_d": rem_h / hours_per_day,
                "req_h": req_h, "req_d": req_h / hours_per_day,
                "tot_h": tot_h, "tot_d": tot_h / hours_per_day,
                "diff_h": diff_h, "diff_d": diff_h / hours_per_day,
            })
        return {
            "workcenter_id": wc.id,
            "name": wc.name,
            "overload": overloaded,
            "cells": cells,
        }

    @api.model
    def set_capacity_factor(self, workcenter_id, year, month, factor,
                            start_year=False, start_month=False):
        """Upsert the monthly capacity factor and return the recomputed
        row so the grid can refresh in place. factor == 1.0 removes the
        override (back to standard capacity, BRD §14)."""
        workcenter_id = int(workcenter_id)
        year, month = int(year), int(month)
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            factor = 0.0
        if not factor > 0:
            raise UserError(
                _("The capacity factor must be a positive number."))

        Factor = self.env["mrp.ltp.capacity.factor"]
        line = Factor.search([
            ("workcenter_id", "=", workcenter_id),
            ("year", "=", year),
            ("month", "=", month),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if abs(factor - 1.0) < 1e-9:
            line.unlink()
        elif line:
            line.factor = factor
        else:
            Factor.create({
                "workcenter_id": workcenter_id,
                "year": year,
                "month": month,
                "factor": factor,
            })

        # recompute just this workcenter over the currently shown window
        Line = self.env["mrp.ltp.line"]
        if start_year and start_month:
            sy, sm = int(start_year), int(start_month)
        else:
            sy, sm = Line._current_period()
        periods = Line._periods(sy, sm)
        wc = self.env["mrp.workcenter"].browse(workcenter_id)
        row = self._build_row(
            wc, periods,
            self._capacity_map(wc, periods),
            self._workload_map(wc, periods),
            self._required_load_map(periods, wc),
            self._factor_map(wc, periods))
        return {"row": row}

    # ------------------------------------------------------------------
    # Monthly capacity factors (BRD §2/§15): default 1.0 per
    # (workcenter, month); only overrides are stored.
    # ------------------------------------------------------------------

    @api.model
    def _factor_map(self, workcenters, periods):
        """{(wc_id, abs_month): factor} — 1.0 when no override exists."""
        Line = self.env["mrp.ltp.line"]
        period_min = periods[0][0] * 100 + periods[0][1]
        period_max = periods[-1][0] * 100 + periods[-1][1]
        recs = self.env["mrp.ltp.capacity.factor"].search_read([
            ("workcenter_id", "in", workcenters.ids),
            ("period", ">=", period_min),
            ("period", "<=", period_max),
            ("company_id", "=", self.env.company.id),
        ], ["workcenter_id", "year", "month", "factor"])
        return {
            (rec["workcenter_id"][0],
             Line._abs_month(rec["year"], rec["month"])): rec["factor"]
            for rec in recs
        }

    # ------------------------------------------------------------------
    # Capacity: working-calendar hours, never hard-coded (AC-16)
    # ------------------------------------------------------------------

    @api.model
    def _tz(self):
        return pytz.timezone(self.env.user.tz or "UTC")

    @api.model
    def _month_bounds(self, year, month):
        """[start, end) of a calendar month as timezone-aware UTC datetimes."""
        tz = self._tz()
        next_idx = year * 12 + month  # absolute index of the following month
        start = tz.localize(datetime(year, month, 1)).astimezone(pytz.UTC)
        end = tz.localize(
            datetime(next_idx // 12, next_idx % 12 + 1, 1)).astimezone(pytz.UTC)
        return start, end

    @api.model
    def _work_intervals(self, workcenter, start, end):
        """Flat [(start, end)] working intervals of the workcenter's calendar
        inside the given (aware UTC) range, honoring leaves."""
        calendar = workcenter.resource_calendar_id
        if not calendar or not start or not end or end <= start:
            return []
        batch = calendar._work_intervals_batch(
            start, end, resources=workcenter.resource_id)
        intervals = []
        for _key, items in batch.items():
            for item in items:
                intervals.append((item[0], item[1]))
        return intervals

    @api.model
    def _working_hours(self, workcenter, start, end, clip_start=None,
                       clip_end=None):
        """Working hours inside [start, end) optionally clipped to
        [clip_start, clip_end) — used both for capacity and for splitting a
        workorder's load across months."""
        total = 0.0
        for iv_start, iv_end in self._work_intervals(workcenter, start, end):
            if clip_start is not None:
                iv_start = max(iv_start, clip_start)
            if clip_end is not None:
                iv_end = min(iv_end, clip_end)
            if iv_end > iv_start:
                total += (iv_end - iv_start).total_seconds()
        return total / 3600.0

    @api.model
    def _capacity_map(self, workcenters, periods):
        """{(wc_id, abs_month): hours} — calendar hours x parallel capacity
        (default mrp.workcenter.capacity line) x time efficiency."""
        Line = self.env["mrp.ltp.line"]
        cap_map = {}
        for wc in workcenters:
            if not wc.resource_calendar_id:
                continue
            # Odoo 19: no scalar `capacity` field on the workcenter — the
            # generic (product-less) mrp.workcenter.capacity line is the
            # parallel-capacity default; fall back to 1 when absent.
            parallel = 1.0
            for cap_line in wc.capacity_ids:
                if not cap_line.product_id:
                    parallel = cap_line.capacity or 1.0
                    break
            factor = parallel * (wc.time_efficiency or 100.0) / 100.0
            for year, month in periods:
                start, end = self._month_bounds(year, month)
                hours = self._working_hours(wc, start, end) * factor
                cap_map[(wc.id, Line._abs_month(year, month))] = hours
        return cap_map

    # ------------------------------------------------------------------
    # Workload: planned mrp.workorder durations, split across months by
    # their share of working time in each month (BRD §9)
    # ------------------------------------------------------------------

    @api.model
    def _workload_map(self, workcenters, periods):
        Line = self.env["mrp.ltp.line"]
        first_idx = Line._abs_month(*periods[0])
        last_idx = Line._abs_month(*periods[-1])
        domain = [
            ("workcenter_id", "in", workcenters.ids),
            ("state", "not in", list(WO_CLOSED_STATES)),
            ("production_id.state", "in", list(MO_OPEN_STATES)),
        ]
        workorders = self.env["mrp.workorder"].search_read(domain, [
            "workcenter_id", "date_start", "date_finished", "duration_expected",
        ])
        wc_by_id = {wc.id: wc for wc in workcenters}
        load_map = {}
        for wo in workorders:
            wc_id = wo["workcenter_id"][0]
            wc = wc_by_id.get(wc_id)
            hours = (wo["duration_expected"] or 0.0) / 60.0
            if not wc or not hours:
                continue
            start = (pytz.UTC.localize(wo["date_start"])
                     if wo["date_start"] else None)
            end = (pytz.UTC.localize(wo["date_finished"])
                   if wo["date_finished"] else None)
            total_work = (self._working_hours(wc, start, end)
                          if start and end and end > start else 0.0)
            if total_work > 0:
                # proportional split: each month gets the share of working
                # time the operation occupies inside it
                for year, month in periods:
                    ms, me = self._month_bounds(year, month)
                    share = self._working_hours(
                        wc, start, end, clip_start=ms, clip_end=me)
                    if share:
                        key = (wc_id, Line._abs_month(year, month))
                        load_map[key] = load_map.get(key, 0.0) + (
                            hours * share / total_work)
            else:
                # unscheduled or zero-length operation: put the whole load on
                # the month of its (planned) start
                anchor = start or self._month_bounds(*periods[0])[0]
                idx = Line._abs_month(*self._month_pair(anchor))
                idx = min(max(idx, first_idx), last_idx)
                key = (wc_id, idx)
                load_map[key] = load_map.get(key, 0.0) + hours
        return load_map

    @api.model
    def _month_pair(self, dt):
        """(year, month) of an aware datetime in the user timezone."""
        local = dt.astimezone(self._tz())
        return local.year, local.month

    # ------------------------------------------------------------------
    # Required production (BRD §10/§20): demand not yet covered by stock,
    # open supply or existing MOs — routed through BOM operations into
    # workcenter hours. Never double-counted with planned production.
    # ------------------------------------------------------------------

    @api.model
    def _required_qty_map(self, periods):
        """{(product_id, abs_month): qty} — per product/month the quantity
        still needing production: IM = orders - stock - incoming supply
        (incl. open MOs). This is exactly "what the existing production
        does not yet cover" — an order of 100 with an MO of 10 yields 90.
        PM is deliberately NOT added: it is planning intent shown on the
        planning screen, not demand, and counting it would double-count
        quantities already covered by MOs."""
        Line = self.env["mrp.ltp.line"]
        products = self.env["product.product"].search([
            ("product_tmpl_id.x_long_term_production_planning", "=", True)])
        req_map = {}
        for row in Line._compute_rows(products, periods, False):
            for cell in row["cells"]:
                if cell["im"] > 0:
                    req_map[(row["product_id"],
                             Line._abs_month(cell["year"], cell["month"]))] = (
                        cell["im"])
        return req_map

    @api.model
    def _required_load_map(self, periods, workcenters):
        """{(wc_id, abs_month): hours} — required quantities converted to
        workcenter hours via the product's (normal) BOM operations:
        hours = req_qty x op.time_cycle / 60 / bom.product_qty.
        First BOM level only; products without a BOM or without operations
        on the shown workcenters contribute no load."""
        Line = self.env["mrp.ltp.line"]
        req_map = self._required_qty_map(periods)
        if not req_map:
            return {}
        product_ids = {pid for pid, _m in req_map}
        products = self.env["product.product"].browse(product_ids)
        boms = self.env["mrp.bom"]._bom_find(products)
        # _bom_find returns {product: bom} — normalize by product id
        bom_by_pid = {}
        for key, bom in boms.items():
            bom_by_pid[getattr(key, "id", key)] = bom
        req_by_pid = {}
        for (pid, abs_month), qty in req_map.items():
            req_by_pid.setdefault(pid, []).append((abs_month, qty))
        wc_ids = set(workcenters.ids)
        load_map = {}
        for product in products:
            bom = bom_by_pid.get(product.id)
            if not bom or bom.type != "normal":
                continue
            per_unit = {}
            for op in bom.operation_ids:
                wc_id = op.workcenter_id.id
                if wc_id not in wc_ids:
                    continue
                per_unit[wc_id] = per_unit.get(wc_id, 0.0) + (
                    (op.time_cycle or 0.0) / 60.0 / (bom.product_qty or 1.0))
            if not per_unit:
                continue
            for abs_month, qty in req_by_pid.get(product.id, ()):
                for wc_id, hours_per_unit in per_unit.items():
                    key = (wc_id, abs_month)
                    load_map[key] = load_map.get(key, 0.0) + qty * hours_per_unit
        return load_map
