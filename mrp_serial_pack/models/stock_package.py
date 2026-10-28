# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPackage(models.Model):
    _inherit = "stock.package"

    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order",
        readonly=True, copy=False, index="btree_not_null",
        help="Bu paketi Veri Al işlemiyle oluşturan üretim emri.")

    def _get_pending_pack_move_lines(self):
        """Return not-done/cancelled move lines targeted to this package."""
        self.ensure_one()
        return self.env["stock.move.line"].search([
            ("result_package_id", "=", self.id),
            ("state", "not in", ("done", "cancel")),
        ])

    def _get_pack_fill(self, product=None):
        """Return the number of product units currently linked to the package.

        Pending produced units exist as (not yet done) move lines with
        ``result_package_id`` pointing here; already produced units exist as
        quants inside the package. Both are counted so the fill level stays
        correct before and after the MO is marked done.
        """
        self.ensure_one()
        qty = 0.0
        for move_line in self._get_pending_pack_move_lines():
            if product and move_line.product_id != product:
                continue
            qty += move_line.product_uom_id._compute_quantity(
                move_line.quantity, move_line.product_id.uom_id)
        for quant in self.quant_ids:
            if quant.quantity <= 0 or (product and quant.product_id != product):
                continue
            qty += quant.quantity
        return qty
