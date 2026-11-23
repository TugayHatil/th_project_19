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
            product = line.product_id
            pid = product.id if isinstance(product.id, int) else \
                (product._origin.id if product._origin else False)
            if not pid:
                line.mpn_ids = False
                continue
            # Onchange baglaminda o2m okumasi cache'den bos donebiliyor;
            # acik search kullan.
            available = self.env['product.manufacturer'].search(
                [('product_id', '=', pid)])
            if len(available) == 1:
                line.mpn_ids = available
            else:
                # urun degisince eski urunun MPN'leri kalmasin
                line.mpn_ids = line.mpn_ids.filtered(
                    lambda m: m.id in available.ids)
