# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductSubType(models.Model):
    _name = 'product.sub.type'
    _description = 'Alt Ürün Türü'
    _inherit = ['product.extra.definition.mixin',
                'mail.thread', 'mail.activity.mixin']
    _product_field_name = 'sub_type_id'

    name = fields.Char(string='Alt Ürün Türü', tracking=True)
    description = fields.Char(string='Açıklama', tracking=True)
    product_count = fields.Integer(
        string='Ürünler', compute='_compute_product_count')

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu alt ürün türü zaten tanımlı.',
    )
