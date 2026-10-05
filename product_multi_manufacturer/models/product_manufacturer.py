# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductManufacturer(models.Model):
    _name = 'product.manufacturer'
    _description = 'Product Manufacturer'
    _order = 'product_id, manufacturer_id, manufacturer_code'

    product_id = fields.Many2one(
        'product.product',
        string='Ürün',
        required=True,
        ondelete='cascade',
    )
    manufacturer_code = fields.Char(
        string='Üretici Kodu',
        required=True,
    )
    manufacturer_id = fields.Many2one(
        'res.partner',
        string='Üretici',
        required=True,
        domain="[('is_manufacturer', '=', True)]",
        context={'default_is_manufacturer': True},
    )
    note = fields.Char(
        string='Not',
    )
    state = fields.Selection(
        [
            ('not_for_new_design', 'Not For New Design'),
            ('recommended_for_new_design', 'Recommended For New Design'),
            ('released_to_production', 'Relased To Production'),
            ('prototype', 'Prototype'),
        ],
        string='Durumu',
        required=True,
    )

    _sql_constraints = [
        (
            'product_manufacturer_code_unique',
            'unique(product_id, manufacturer_id, manufacturer_code)',
            'Aynı ürün, üretici ve üretici kodu kombinasyonu daha önce tanımlanmıştır.'
        ),
    ]
