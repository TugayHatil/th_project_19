# -*- coding: utf-8 -*-
from odoo import fields, models

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
