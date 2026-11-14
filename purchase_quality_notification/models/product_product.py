# -*- coding: utf-8 -*-
from odoo import api, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        Point = self.env['quality.point'].with_context(active_test=False).sudo()
        for product in products:
            template = product.product_tmpl_id
            if not template.quality_purchase_ok:
                continue
            point = Point.search(
                [('auto_purchase_tmpl_id', '=', template.id)], limit=1)
            if point:
                point.write({'product_ids': [(4, product.id)]})
            else:
                template._sync_purchase_quality_point()
        return products
