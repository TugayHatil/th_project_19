# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductMaterialGroup(models.Model):
    _name = 'product.material.group'
    _description = 'Mal Grubu'
    _order = 'name'

    name = fields.Char(string='Mal Grubu', required=True)
    active = fields.Boolean(string='Aktif', default=True)

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu mal grubu zaten tanımlı.',
    )
