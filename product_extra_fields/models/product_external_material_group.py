# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductExternalMaterialGroup(models.Model):
    _name = 'product.external.material.group'
    _description = 'Harici Mal Grubu'
    _inherit = 'product.extra.definition.mixin'

    name = fields.Char(string='Harici Mal Grubu')

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu harici mal grubu zaten tanımlı.',
    )
