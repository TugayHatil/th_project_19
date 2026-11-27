# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .product_supplierinfo_shipping_delay import SHIPPING_TYPES


class ProductSupplierinfo(models.Model):
    _inherit = 'product.supplierinfo'

    shipping_delay_ids = fields.One2many(
        'product.supplierinfo.shipping.delay', 'supplierinfo_id',
        string='Sevk Süreleri', copy=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_shipping_delay_lines()
        return records

    def _ensure_shipping_delay_lines(self):
        """Eksik sevk türleri için süre satırları oluşturur."""
        Delay = self.env['product.supplierinfo.shipping.delay']
        vals_list = []
        for supplierinfo in self:
            existing = set(supplierinfo.shipping_delay_ids.mapped('shipping_type'))
            vals_list += [
                {'supplierinfo_id': supplierinfo.id, 'shipping_type': shipping_type}
                for shipping_type, _label in SHIPPING_TYPES if shipping_type not in existing
            ]
        if vals_list:
            Delay.create(vals_list)
