# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    # BRD §7.3 — inverse side of purchase.request.line.need_move_ids.
    # A raw material move linked here has already been transferred to a
    # purchase request and must not be requested again (BRD §7.2 dedup).
    purchase_need_request_line_ids = fields.Many2many(
        comodel_name="purchase.request.line",
        relation="purchase_request_line_need_move_rel",
        column1="move_id",
        column2="purchase_request_line_id",
        string="Satınalma Talebi Satırları",
        copy=False,
        readonly=True,
    )

    # fields that actually feed the plan — skipping the rest keeps the
    # version bump off the hot path of high-frequency move writes
    _PLAN_FIELDS = {
        "state", "product_id", "product_uom", "product_uom_qty",
        "location_id", "location_dest_id", "date", "date_deadline",
        "warehouse_id", "picking_id", "raw_material_production_id",
        "qty_picked", "picked", "sale_line_id",
    }

    # any move change can alter the material-need plan — bump the shared
    # plan version so cached plans rebuild on the next request
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if self._PLAN_FIELDS & set(vals):
            self.env["mrp.purchase.need"]._bump_plan_version()
        return res

    def unlink(self):
        res = super().unlink()
        self.env["mrp.purchase.need"]._bump_plan_version()
        return res


class StockQuant(models.Model):
    _inherit = "stock.quant"

    _PLAN_FIELDS = {
        "quantity", "reserved_quantity", "location_id",
        "product_id", "product_uom_id",
    }

    # on-hand balances feed the plan walk directly — inventory
    # adjustments and quant reservations must refresh the cached plan
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if self._PLAN_FIELDS & set(vals):
            self.env["mrp.purchase.need"]._bump_plan_version()
        return res
