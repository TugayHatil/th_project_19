# -*- coding: utf-8 -*-
from odoo import api, fields, models

SHIPPING_TYPES = [
    ('sea', 'Denizyolu'),
    ('air', 'Havayolu'),
    ('land', 'Karayolu'),
    ('rail', 'Demiryolu'),
]


class ProductSupplierinfoShippingDelay(models.Model):
    _name = 'product.supplierinfo.shipping.delay'
    _description = 'Tedarikçi Sevk Süresi'
    _order = 'id'

    supplierinfo_id = fields.Many2one(
        'product.supplierinfo', string='Tedarikçi Fiyat Satırı',
        required=True, ondelete='cascade', index=True)
    shipping_type = fields.Selection(
        SHIPPING_TYPES, string='Sevk Türü', required=True)
    days = fields.Integer(
        string='Süre (Gün)', required=True, default=0,
        help='Beklenen yükleme tarihi, beklenen geliş tarihinden bu kadar gün geriye alınarak hesaplanır.')

    _supplierinfo_shipping_type_uniq = models.Constraint(
        'unique(supplierinfo_id, shipping_type)',
        'Her sevk türü için yalnızca bir süre satırı tanımlanabilir.')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.supplierinfo_id._recompute_po_loading_dates()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'days' in vals or 'shipping_type' in vals:
            self.supplierinfo_id._recompute_po_loading_dates()
        return res

    def unlink(self):
        supplierinfos = self.supplierinfo_id
        res = super().unlink()
        supplierinfos._recompute_po_loading_dates()
        return res
