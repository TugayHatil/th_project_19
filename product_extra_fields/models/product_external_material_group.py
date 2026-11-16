# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductExternalMaterialGroup(models.Model):
    _name = 'product.external.material.group'
    _description = 'Harici Mal Grubu'
    _inherit = 'product.extra.definition.mixin'
    _product_field_name = 'external_material_group_id'

    name = fields.Char(string='Harici Mal Grubu')
    description = fields.Char(string='Tanımı')
    product_count = fields.Integer(
        string='Ürünler', compute='_compute_product_count')

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu harici mal grubu zaten tanımlı.',
    )
