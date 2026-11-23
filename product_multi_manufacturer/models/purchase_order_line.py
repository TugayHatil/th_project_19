# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    mpn_ids = fields.Many2many(
        'product.manufacturer',
        'purchase_order_line_product_manufacturer_rel',
        'order_line_id',
        'manufacturer_row_id',
        string='MPN',
        domain="[('product_id', '=', product_id)]",
    )

    @api.onchange('product_id')
    def _onchange_product_id_mpn(self):
        for line in self:
            available = line.product_id.manufacturer_ids
            if len(available) == 1:
                line.mpn_ids = available
            else:
                # ürün değişince eski ürünün MPN'leri kalmasın
                line.mpn_ids = line.mpn_ids.filtered(
                    lambda m: m.id in available.ids)
