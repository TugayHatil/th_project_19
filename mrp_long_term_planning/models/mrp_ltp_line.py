# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import api, fields, models
from odoo.osv import expression

MONTHS = range(1, 13)
MOVE_OPEN_STATES = ("confirmed", "waiting", "assigned", "partially_available")


class MrpLtpLine(models.Model):
    """Persistent storage for the planner-editable PM (planned quantity).

    OS/SM/GM are intentionally NOT stored: they are computed live from sales,
    stock and incoming moves every time the grid is loaded, so the plan never
    goes stale. Only the user input (planned_qty) survives reloads (BRD §17).
    """

    _name = "mrp.ltp.line"
    _description = "Long-Term Production Planning Line"
    _order = "product_id, year, month"

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
    planned_qty = fields.Float(
        string="Planned Quantity", digits="Product Unit", default=0.0,
    )

    _sql_constraints = [
        ("check_month", "CHECK(month BETWEEN 1 AND 12)",
         "Month must be between 1 and 12."),
        ("check_qty", "CHECK(planned_qty >= 0)",
         "Planned quantity cannot be negative."),
    ]

    def init(self):
        # A NULL warehouse_id represents the "all warehouses" plan; COALESCE
        # keeps the unique index strict for those rows too.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mrp_ltp_line_product_period_uniq
            ON mrp_ltp_line (company_id, product_id, COALESCE(warehouse_id, 0), year, month)
        """)

    # ------------------------------------------------------------------
    # RPC service layer — consumed by the OWL planning screen
    # ------------------------------------------------------------------

    @api.model
    def get_planning_filters(self):
        today = fields.Date.context_today(self)
        return {
            "current_year": today.year,
            "years": list(range(today.year - 2, today.year + 6)),
            "categories": self.env["product.category"].search_read(
                [], ["complete_name"], order="complete_name"),
            "warehouses": self.env["stock.warehouse"].search_read(
                [("company_id", "in", self.env.companies.ids)],
                ["name", "code"], order="name"),
        }

    @api.model
    def get_planning_grid(self, year, warehouse_id=False, category_id=False,
                          query="", needs_only=False, offset=0, limit=80):
        """Return one page of planning rows for the OWL grid.

        Server-side filtering + pagination: never ship the whole product set
        (BRD §18). With needs_only, the IM>0 flag is computed for every
        matching product before slicing the page.
        """
        year = int(year)
        offset, limit = int(offset), int(limit)
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
            rows = self._compute_rows(products, year, warehouse_id or False)
            rows = [row for row in rows
                    if any(cell["im"] > 0 for cell in row["cells"])]
            return {"total": len(rows), "rows": rows[offset:offset + limit]}

        total = Product.search_count(domain)
        products = Product.search(
            domain, order="name, id", offset=offset, limit=limit)
        return {"total": total, "rows": self._compute_rows(
            products, year, warehouse_id or False)}

    @api.model
    def set_planned_qty(self, product_id, year, month,
                        warehouse_id=False, planned_qty=0.0):
        """Upsert the PM value and return the recomputed row so the grid can
        refresh the DS chain of that product."""
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
        rows = self._compute_rows(product, year, warehouse_id or False)
        return {"row": rows[0] if rows else None}

    # ------------------------------------------------------------------
    # Computation helpers
    # ------------------------------------------------------------------

    @api.model
    def _compute_rows(self, products, year, warehouse_id):
        products = products.exists()
        if not products:
            return []
        product_ids = products.ids
        stock_map = self._opening_stock_map(product_ids, warehouse_id)
        os_map = self._order_qty_map(product_ids, year, warehouse_id)
        gm_map = self._incoming_qty_map(product_ids, year, warehouse_id)
        pm_map = self._planned_qty_map(product_ids, year, warehouse_id)
        rows = []
        for product in products:
            pid = product.id
            rows.append({
                "product_id": pid,
                "name": product.name,
                "code": product.default_code or "",
                "uom": product.uom_id.name,
                "cells": self._build_cells(
                    stock_map.get(pid, 0.0),
                    {m: os_map.get((pid, m), 0.0) for m in MONTHS},
                    {m: gm_map.get((pid, m), 0.0) for m in MONTHS},
                    {m: pm_map.get((pid, m), 0.0) for m in MONTHS},
                ),
            })
        return rows

    @staticmethod
    def _build_cells(opening_stock, order_qtys, incoming_qtys, planned_qtys):
        """12-month rolling plan (BRD §9): the DS of month n is the opening
        stock SM of month n+1.

            IM = max(0, OS - SM - GM)
            DS = SM + GM + PM - OS
        """
        cells = []
        sm = opening_stock
        for month in MONTHS:
            os_ = order_qtys.get(month, 0.0)
            gm_ = incoming_qtys.get(month, 0.0)
            pm_ = planned_qtys.get(month, 0.0)
            im_ = max(0.0, os_ - sm - gm_)
            ds_ = sm + gm_ + pm_ - os_
            cells.append({
                "month": month, "os": os_, "sm": sm, "gm": gm_,
                "im": im_, "pm": pm_, "ds": ds_,
            })
            sm = ds_
        return cells

    @staticmethod
    def _year_window(year):
        return f"{year}-01-01", f"{year + 1}-01-01"

    @api.model
    def _period_month(self, value):
        """Month index (1-12) of a date/datetime value; datetimes are
        converted to the user timezone."""
        if isinstance(value, datetime):
            return fields.Datetime.context_timestamp(self, value).month
        if isinstance(value, str):
            value = fields.Date.from_string(value[:10])
        return value.month

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
    def _order_qty_map(self, product_ids, year, warehouse_id):
        """OS: remaining (ordered - delivered) quantity of confirmed sale
        orders, bucketed by the promised month (commitment_date, falling back
        to the order date)."""
        start, end = self._year_window(year)
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
        order_month = {
            order["id"]: self._period_month(
                order["commitment_date"] or order["date_order"])
            for order in orders
        }
        os_map = {}
        lines = self.env["sale.order.line"].search_read([
            ("order_id", "in", list(order_month)),
            ("product_id", "in", product_ids),
        ], ["product_id", "product_uom_qty", "qty_delivered", "order_id"])
        for line in lines:
            remaining = max(0.0, line["product_uom_qty"] - line["qty_delivered"])
            if not remaining:
                continue
            key = (line["product_id"][0], order_month[line["order_id"][0]])
            os_map[key] = os_map.get(key, 0.0) + remaining
        return os_map

    @api.model
    def _incoming_qty_map(self, product_ids, year, warehouse_id):
        """GM: open incoming stock moves (planned production, open purchases,
        other supply), bucketed by their scheduled month."""
        start, end = self._year_window(year)
        domain = [
            ("product_id", "in", product_ids),
            ("state", "in", list(MOVE_OPEN_STATES)),
            ("date", ">=", start),
            ("date", "<", end),
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
        gm_map = {}
        for move in self.env["stock.move"].search_read(
                domain, ["product_id", "product_uom_qty", "quantity", "date"]):
            remaining = max(0.0, move["product_uom_qty"] - move["quantity"])
            if not remaining:
                continue
            month = self._period_month(move["date"])
            key = (move["product_id"][0], month)
            gm_map[key] = gm_map.get(key, 0.0) + remaining
        return gm_map

    @api.model
    def _planned_qty_map(self, product_ids, year, warehouse_id):
        """PM: stored planner input for the product/year/warehouse scope."""
        domain = [
            ("product_id", "in", product_ids),
            ("year", "=", int(year)),
            ("warehouse_id", "=", warehouse_id or False),
            ("company_id", "=", self.env.company.id),
        ]
        pm_map = {}
        for line in self.search_read(domain, ["product_id", "month", "planned_qty"]):
            pm_map[(line["product_id"][0], line["month"])] = line["planned_qty"]
        return pm_map
