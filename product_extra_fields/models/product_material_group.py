# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductMaterialGroup(models.Model):
    _name = 'product.material.group'
    _description = 'Mal Grubu'
    _inherit = 'product.extra.definition.mixin'
    _product_field_name = 'material_group_id'

    name = fields.Char(string='Mal Grubu')
    description = fields.Char(string='Tanımı')
    product_count = fields.Integer(
        string='Ürünler', compute='_compute_product_count')

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu mal grubu zaten tanımlı.',
    )
