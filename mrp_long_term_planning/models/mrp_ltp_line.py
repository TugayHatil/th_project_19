# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import api, fields, models
from odoo.osv import expression

PERIOD_COUNT = 12
# "draft" included: draft receipts/transfers are already planned supply
# (BRD §8) and must feed GM.
MOVE_OPEN_STATES = ("draft", "confirmed", "waiting", "assigned",
                    "partially_available")
MO_OPEN_STATES = ("draft", "confirmed", "progress", "to_close")


class MrpLtpLine(models.Model):
    """Persistent storage for the planner-editable PM (planned quantity).

    OS/SM/GM are intentionally NOT stored: they are computed live from sales,
    stock and incoming moves every time the grid is loaded, so the plan never
    goes stale. Only the user input (planned_qty) survives reloads (BRD §17).
    """

    _name = "mrp.ltp.line"
    _description = "Long-Term Production Planning Line"
    _order = "product_id, period"

    product_id = fields.Many2one(
        "product.product", string="Product", required=True, index=True,
        ondelete="cascade",
    )
    # Empty warehouse = plan row valid for "all warehouses" (global scope).
    warehouse_id = fields.Many2one("stock.warehouse", string="Warehouse", index=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company,
    )
    year = fields.Integer(required=True, index=True)
    month = fields.Integer(required=True)
    # YYYYMM — monotonic key used for window filtering and roll-over.
    period = fields.Integer(compute="_compute_period", store=True, index=True)
    planned_qty = fields.Float(
        string="Planned Quantity", digits="Long-Term Planning Quantity",
        default=0.0,
    )

    _sql_constraints = [
        ("check_month", "CHECK(month BETWEEN 1 AND 12)",
         "Month must be between 1 and 12."),
        ("check_qty", "CHECK(planned_qty >= 0)",
         "Planned quantity cannot be negative."),
    ]

    @api.depends("year", "month")
    def _compute_period(self):
        for line in self:
            line.period = line.year * 100 + line.month

    def init(self):
        # A NULL warehouse_id represents the "all warehouses" plan; COALESCE
        # keeps the unique index strict for those rows too.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mrp_ltp_line_product_period_uniq
            ON mrp_ltp_line (company_id, product_id, COALESCE(warehouse_id, 0), period)
        """)

    # ------------------------------------------------------------------
    # Planning period — rolling 12-month window (BRD revision):
    # the first column is always the current server month, never a fixed
    # calendar year. All cell data is keyed by the real (year, month) pair.
    # ------------------------------------------------------------------

    @api.model
    def _current_period(self):
        """Current month (year, month) in the user's timezone."""
        today = fields.Date.context_today(self)
        return today.year, today.month

    @staticmethod
    def _periods(start_year, start_month, count=PERIOD_COUNT):
        """[(year, month), ...] of `count` consecutive months."""
        start_idx = start_year * 12 + start_month - 1
        return [
            ((start_idx + i) // 12, (start_idx + i) % 12 + 1)
            for i in range(count)
        ]

    @staticmethod
    def _abs_month(year, month):
        """Monotonic month index — single key across year boundaries."""
        return year * 12 + month - 1

    def _period_window(self, periods):
        """[start, end) date strings covering the whole period list."""
        sy, sm = periods[0]
        end_idx = self._abs_month(*periods[-1]) + 1
        return f"{sy}-{sm:02d}-01", f"{end_idx // 12}-{end_idx % 12 + 1:02d}-01"

    # ------------------------------------------------------------------
    # RPC service layer — consumed by the OWL planning screen
    # ------------------------------------------------------------------

    @api.model
    def _period_payload(self, periods):
        return [{"year": y, "month": m} for y, m in periods]

    @api.model
    def get_planning_filters(self):
        periods = self._periods(*self._current_period())
        return {
            "periods": self._period_payload(periods),
            # grid quantity digits are user-configurable via
            # Settings > Technical > Decimal Accuracy
            "qty_precision": self.env["decimal.precision"].precision_get(
                "Long-Term Planning Quantity"),
            "categories": self.env["product.category"].search_read(
                [], ["complete_name"], order="complete_name"),
            "warehouses": self.env["stock.warehouse"].search_read(
                [("company_id", "in", self.env.companies.ids)],
                ["name", "code"], order="name"),
        }

    @api.model
    def get_planning_grid(self, warehouse_id=False, category_id=False,
                          query="", needs_only=False, offset=0, limit=80):
        """Return one page of planning rows for the OWL grid.

        Server-side filtering + pagination: never ship the whole product set
        (BRD §18). With needs_only, the IM>0 flag is computed for every
        matching product before slicing the page.
        """
        offset, limit = int(offset), int(limit)
        periods = self._periods(*self._current_period())
        payload = {"periods": self._period_payload(periods)}

        domain = [("product_tmpl_id.x_long_term_production_planning", "=", True)]
        if category_id:
            domain = expression.AND(
                [domain, [("categ_id", "child_of", int(category_id))]])
        if query and query.strip():
            domain = expression.AND([domain, [
                "|", ("name", "ilike", query.strip()),
                ("default_code", "ilike", query.strip()),
            ]])

        Product = self.env["product.product"]
        if needs_only:
            products = Product.search(domain, order="name, id")
            rows = self._compute_rows(products, periods, warehouse_id or False)
            rows = [row for row in rows
                    if any(cell["im"] > 0 for cell in row["cells"])]
            payload.update(total=len(rows), rows=rows[offset:offset + limit])
            return payload

        products = Product.search(
            domain, order="name, id", offset=offset, limit=limit)
        payload.update(
            total=Product.search_count(domain),
            rows=self._compute_rows(products, periods, warehouse_id or False),
        )
        return payload

    @api.model
    def set_planned_qty(self, product_id, year, month,
                        warehouse_id=False, planned_qty=0.0):
        """Upsert the PM value for the real (year, month) period and return
        the recomputed row so the grid can refresh the DS chain."""
        product_id = int(product_id)
        year, month = int(year), int(month)
        qty = max(0.0, float(planned_qty or 0.0))
        line = self.search([
            ("product_id", "=", product_id),
            ("warehouse_id", "=", warehouse_id or False),
            ("year", "=", year),
            ("month", "=", month),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if line:
            line.planned_qty = qty
        else:
            self.create({
                "product_id": product_id,
                "warehouse_id": warehouse_id or False,
                "year": year,
                "month": month,
                "planned_qty": qty,
            })
        product = self.env["product.product"].browse(product_id)
        periods = self._periods(*self._current_period())
        rows = self._compute_rows(product, periods, warehouse_id or False)
        return {"row": rows[0] if rows else None}

    # ------------------------------------------------------------------
    # Computation helpers
    # ------------------------------------------------------------------

    @api.model
    def _compute_rows(self, products, periods, warehouse_id):
        products = products.exists()
        if not products:
            return []
        product_ids = products.ids
        stock_map = self._opening_stock_map(product_ids, warehouse_id)
        os_map = self._order_qty_map(product_ids, periods, warehouse_id)
        gm_map = self._incoming_qty_map(product_ids, periods, warehouse_id)
        pm_map = self._planned_qty_map(product_ids, periods, warehouse_id)
        rows = []
        for product in products:
            rows.append({
                "product_id": product.id,
                "name": product.name,
                "code": product.default_code or "",
                "uom": product.uom_id.name,
                "cells": self._build_cells(
                    periods, product.id, stock_map.get(product.id, 0.0),
                    os_map, gm_map, pm_map),
            })
        return rows

    def _build_cells(self, periods, product_id, opening_stock,
                     order_qtys, incoming_qtys, planned_qtys):
        """Rolling plan over the given (year, month) periods (BRD §9): the
        DS of a month is the opening stock SM of the next one. All quantity
        maps are keyed by (product_id, absolute-month-index).

            IM = max(0, OS - SM - GM)
            DS = SM + GM + PM - OS
        """
        cells = []
        sm = opening_stock
        for year, month in periods:
            key = (product_id, self._abs_month(year, month))
            os_ = order_qtys.get(key, 0.0)
            gm_ = incoming_qtys.get(key, 0.0)
            pm_ = planned_qtys.get(key, 0.0)
            im_ = max(0.0, os_ - sm - gm_)
            ds_ = sm + gm_ + pm_ - os_
            cells.append({
                "year": year, "month": month,
                "os": os_, "sm": sm, "gm": gm_,
                "im": im_, "pm": pm_, "ds": ds_,
            })
            sm = ds_
        return cells

    @api.model
    def _period_month(self, value):
        """Month index of a date/datetime value as an absolute month key;
        datetimes are converted to the user timezone."""
        if isinstance(value, datetime):
            value = fields.Datetime.context_timestamp(self, value)
        elif isinstance(value, str):
            value = fields.Date.from_string(value[:10])
        return self._abs_month(value.year, value.month)

    # --- data sources (kept as separate services so the OS/GM origins can be
    # extended later, e.g. high-probability opportunities — BRD §8) ---------

    @api.model
    def _opening_stock_map(self, product_ids, warehouse_id):
        """Current on-hand quantity per product (SM of the first month)."""
        domain = [("product_id", "in", product_ids)]
        if warehouse_id:
            warehouse = self.env["stock.warehouse"].browse(int(warehouse_id))
            domain.append(("location_id", "child_of", warehouse.view_location_id.id))
        else:
            domain.append(("location_id.usage", "=", "internal"))
        stock_map = {}
        for product, qty in self.env["stock.quant"]._read_group(
                domain, ["product_id"], ["quantity:sum"]):
            stock_map[product.id] = qty
        return stock_map

    @api.model
    def _order_qty_map(self, product_ids, periods, warehouse_id):
        """OS: remaining (ordered - delivered) quantity of confirmed sale
        orders, bucketed by the promised period (commitment_date, falling
        back to the order date)."""
        start, end = self._period_window(periods)
        domain = [("state", "in", ["sale", "done"])]
        if warehouse_id and "warehouse_id" in self.env["sale.order"]._fields:
            domain.append(("warehouse_id", "=", int(warehouse_id)))
        domain = expression.AND([domain, expression.OR([
            [("commitment_date", ">=", start), ("commitment_date", "<", end)],
            ["&", ("commitment_date", "=", False),
             ("date_order", ">=", start), ("date_order", "<", end)],
        ])])
        orders = self.env["sale.order"].search_read(
            domain, ["commitment_date", "date_order"])
        if not orders:
            return {}
        order_period = {
            order["id"]: self._period_month(
                order["commitment_date"] or order["date_order"])
            for order in orders
        }
        os_map = {}
        lines = self.env["sale.order.line"].search_read([
            ("order_id", "in", list(order_period)),
            ("product_id", "in", product_ids),
        ], ["product_id", "product_uom_qty", "qty_delivered", "order_id"])
        for line in lines:
            remaining = max(0.0, line["product_uom_qty"] - line["qty_delivered"])
            if not remaining:
                continue
            key = (line["product_id"][0], order_period[line["order_id"][0]])
            os_map[key] = os_map.get(key, 0.0) + remaining
        return os_map

    @api.model
    def _incoming_qty_map(self, product_ids, periods, warehouse_id):
        """GM: expected supply per product/month.

        Planned production comes straight from open mrp.production records,
        bucketed by their expected finish date — this is more reliable than
        the finished-product stock.move, whose state/schedule varies with
        the MO state. Other supply (open purchases, inter-warehouse
        receipts) comes from open incoming stock.move records; moves that
        belong to an MO are excluded so nothing is counted twice.
        """
        start, end = self._period_window(periods)
        first_idx = self._abs_month(*periods[0])
        last_idx = self._abs_month(*periods[-1])
        gm_map = {}

        # --- planned production ---------------------------------------
        mo_domain = [
            ("state", "in", list(MO_OPEN_STATES)),
            ("product_id", "in", product_ids),
        ]
        if warehouse_id:
            mo_domain.append((
                "location_dest_id", "child_of",
                self.env["stock.warehouse"].browse(
                    int(warehouse_id)).view_location_id.id))
        mo_fields = ["product_id", "product_qty", "date_finished",
                     "date_start"]
        if "qty_produced" in self.env["mrp.production"]._fields:
            mo_fields.append("qty_produced")
        for mo in self.env["mrp.production"].search_read(mo_domain, mo_fields):
            remaining = mo["product_qty"] - (mo.get("qty_produced") or 0.0)
            if remaining <= 0:
                continue
            date = mo["date_finished"] or mo["date_start"]
            if not date:
                continue
            idx = self._period_month(date)
            if first_idx <= idx <= last_idx:
                key = (mo["product_id"][0], idx)
                gm_map[key] = gm_map.get(key, 0.0) + remaining

        # --- other incoming supply -------------------------------------
        domain = [
            ("product_id", "in", product_ids),
            ("state", "in", list(MOVE_OPEN_STATES)),
            ("date", ">=", start),
            ("date", "<", end),
            # MO-produced moves are already covered by mrp.production above
            ("production_id", "=", False),
        ]
        if warehouse_id:
            location_id = self.env["stock.warehouse"].browse(
                int(warehouse_id)).view_location_id.id
            domain += [
                ("location_dest_id", "child_of", location_id),
                ("location_id", "not child_of", location_id),
            ]
        else:
            domain += [
                ("location_dest_id.usage", "=", "internal"),
                ("location_id.usage", "not in", ("internal", "view")),
            ]
        for move in self.env["stock.move"].search_read(
                domain, ["product_id", "product_uom_qty", "quantity", "date"]):
            remaining = max(0.0, move["product_uom_qty"] - move["quantity"])
            if not remaining:
                continue
            key = (move["product_id"][0], self._period_month(move["date"]))
            gm_map[key] = gm_map.get(key, 0.0) + remaining
        return gm_map

    @api.model
    def _planned_qty_map(self, product_ids, periods, warehouse_id):
        """PM: stored planner input restricted to the visible window.
        Rows outside the window are kept untouched (BRD §9/§13-14)."""
        period_min = periods[0][0] * 100 + periods[0][1]
        period_max = periods[-1][0] * 100 + periods[-1][1]
        domain = [
            ("product_id", "in", product_ids),
            ("period", ">=", period_min),
            ("period", "<=", period_max),
            ("warehouse_id", "=", warehouse_id or False),
            ("company_id", "=", self.env.company.id),
        ]
        pm_map = {}
        for line in self.search_read(
                domain, ["product_id", "year", "month", "planned_qty"]):
            key = (line["product_id"][0],
                   self._abs_month(line["year"], line["month"]))
            pm_map[key] = line["planned_qty"]
        return pm_map

    # ------------------------------------------------------------------
    # Baseline / revision service layer (BRD "Sipariş Teyit, Baseline ve
    # Revizyon Yönetimi")
    # ------------------------------------------------------------------

    @api.model
    def _product_domain(self, category_id=False, query=""):
        domain = [("product_tmpl_id.x_long_term_production_planning", "=", True)]
        if category_id:
            domain = expression.AND(
                [domain, [("categ_id", "child_of", int(category_id))]])
        if query and query.strip():
            domain = expression.AND([domain, [
                "|", ("name", "ilike", query.strip()),
                ("default_code", "ilike", query.strip()),
            ]])
        return domain

    @api.model
    def _revision_payload(self, revision):
        return {
            "id": revision.id,
            "name": revision.name,
            "date": fields.Datetime.to_string(revision.confirm_date),
            "user": revision.user_id.name,
            "period_start": revision.period_start,
        }

    @api.model
    def get_revision_list(self, warehouse_id=False):
        """Revisions of the current warehouse scope for the dropdown (§13)."""
        revisions = self.env["mrp.ltp.revision"].search_read(
            [("warehouse_id", "=", warehouse_id or False),
             ("company_id", "=", self.env.company.id)],
            ["confirm_date", "user_id", "period_start"], order="id desc")
        return [{
            "id": r["id"],
            "name": "#%s" % r["id"],
            "date": r["confirm_date"],
            "user": r["user_id"] and r["user_id"][1] or "",
            "period_start": r["period_start"],
        } for r in revisions]

    @api.model
    def _baseline_lines_map(self, revision):
        """{(product_id, abs_month): {"os","pm","demand"}} from a revision."""
        lines_map = {}
        for line in revision.line_ids:
            key = (line.product_id.id, self._abs_month(line.year, line.month))
            lines_map[key] = {
                "os": line.order_qty,
                "pm": line.planned_qty,
                "demand": line.demand_qty,
            }
        return lines_map

    @api.model
    def get_baseline(self, warehouse_id=False):
        """Latest confirmed baseline for the current scope (§2.2/§8).

        Returns the revision header plus a flat "pid:yyyymm" → values map
        the grid merges into each live cell (Teyitli/Değişim columns).
        """
        revision = self.env["mrp.ltp.revision"].search([
            ("warehouse_id", "=", warehouse_id or False),
            ("company_id", "=", self.env.company.id),
        ], order="id desc", limit=1)
        if not revision:
            return {"revision": False, "lines": {}}
        lines = {
            "%s:%s" % (line.product_id.id, line.year * 100 + line.month): {
                "os": line.order_qty,
                "pm": line.planned_qty,
                "demand": line.demand_qty,
            } for line in revision.line_ids
        }
        return {"revision": self._revision_payload(revision), "lines": lines}

    @api.model
    def confirm_plan(self, warehouse_id=False, category_id=False, query=""):
        """Snapshot the whole visible plan into a new revision (§5/§6/§19).

        Covers every product matching the structural filters — never just
        the current page. Live values are frozen: order (OS), total demand
        and the stored planner input (PM).
        """
        products = self.env["product.product"].search(
            self._product_domain(category_id, query), order="name, id")
        periods = self._periods(*self._current_period())
        rows = self._compute_rows(products, periods, warehouse_id or False)
        Revision = self.env["mrp.ltp.revision"].sudo()
        revision = Revision.create({
            "warehouse_id": warehouse_id or False,
            "period_start": periods[0][0] * 100 + periods[0][1],
        })
        RevLine = self.env["mrp.ltp.revision.line"].sudo()
        RevLine.create([{
            "revision_id": revision.id,
            "product_id": row["product_id"],
            "year": cell["year"],
            "month": cell["month"],
            "order_qty": cell["os"],
            "forecast_qty": 0.0,
            "demand_qty": cell["os"],
            "planned_qty": cell["pm"],
        } for row in rows for cell in row["cells"]])
        return {"revision": self._revision_payload(revision)}

    @api.model
    def get_revision_data(self, revision_id):
        """Read-only view of one stored baseline (§14)."""
        revision = self.env["mrp.ltp.revision"].search(
            [("id", "=", int(revision_id)),
             ("company_id", "=", self.env.company.id)])
        start_year, start_month = divmod(revision.period_start, 100)
        periods = self._periods(start_year, start_month)
        lines_map = self._baseline_lines_map(revision)
        products = revision.line_ids.product_id.sorted("name")
        rows = []
        for product in products:
            cells = []
            for year, month in periods:
                snap = lines_map.get(
                    (product.id, self._abs_month(year, month)))
                cells.append({
                    "year": year, "month": month,
                    "os": snap["os"] if snap else 0.0,
                    "demand": snap["demand"] if snap else 0.0,
                    "pm": snap["pm"] if snap else 0.0,
                })
            rows.append({
                "product_id": product.id,
                "name": product.name,
                "code": product.default_code or "",
                "uom": product.uom_id.name,
                "cells": cells,
            })
        return {
            "revision": self._revision_payload(revision),
            "periods": self._period_payload(periods),
            "rows": rows,
        }

    @api.model
    def _live_snapshot_map(self, periods, warehouse_id, category_id, query):
        """Live order/plan map keyed like _baseline_lines_map."""
        products = self.env["product.product"].search(
            self._product_domain(category_id, query), order="name, id")
        live = {}
        for row in self._compute_rows(products, periods, warehouse_id):
            for cell in row["cells"]:
                key = (row["product_id"],
                       self._abs_month(cell["year"], cell["month"]))
                live[key] = {"os": cell["os"], "pm": cell["pm"]}
        return live, products

    @api.model
    def get_compare_data(self, rev_a_id, rev_b_id=False, warehouse_id=False,
                         category_id=False, query=""):
        """Two-way comparison rows (§15/§16): side A always a stored
        revision; side B a revision or the live plan (rev_b_id falsy).
        Months are aligned on the current 12-month window."""
        Revision = self.env["mrp.ltp.revision"]
        rev_a = Revision.search(
            [("id", "=", int(rev_a_id)),
             ("company_id", "=", self.env.company.id)])
        periods = self._periods(*self._current_period())
        map_a = self._baseline_lines_map(rev_a)
        label_a = {"id": rev_a.id, "name": rev_a.name}
        if rev_b_id:
            rev_b = Revision.search(
                [("id", "=", int(rev_b_id)),
                 ("company_id", "=", self.env.company.id)])
            map_b = self._baseline_lines_map(rev_b)
            products = (rev_a.line_ids | rev_b.line_ids).product_id.sorted("name")
            label_b = {"id": rev_b.id, "name": rev_b.name}
        else:
            map_b, live_products = self._live_snapshot_map(
                periods, warehouse_id or False, category_id, query)
            products = (rev_a.line_ids.product_id | live_products).sorted("name")
            label_b = {"id": 0, "name": "live"}
        rows = []
        for product in products:
            cells = []
            for year, month in periods:
                key = (product.id, self._abs_month(year, month))
                a_qty = map_a.get(key, {}).get("os", 0.0)
                b_qty = map_b.get(key, {}).get("os", 0.0)
                cells.append({
                    "year": year, "month": month,
                    "a": a_qty, "b": b_qty, "delta": b_qty - a_qty,
                })
            rows.append({
                "product_id": product.id,
                "name": product.name,
                "code": product.default_code or "",
                "uom": product.uom_id.name,
                "cells": cells,
            })
        return {
            "a": label_a, "b": label_b,
            "periods": self._period_payload(periods),
            "rows": rows,
        }
