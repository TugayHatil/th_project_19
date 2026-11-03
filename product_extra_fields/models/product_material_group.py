# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductMaterialGroup(models.Model):
    _name = 'product.material.group'
    _description = 'Mal Grubu'
    _inherit = 'product.extra.definition.mixin'

    name = fields.Char(string='Mal Grubu')

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu mal grubu zaten tanımlı.',
    )
