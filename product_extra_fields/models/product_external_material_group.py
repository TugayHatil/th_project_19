# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductExternalMaterialGroup(models.Model):
    _name = 'product.external.material.group'
    _description = 'Harici Mal Grubu'
    _order = 'name'

    name = fields.Char(string='Harici Mal Grubu', required=True)
    active = fields.Boolean(string='Aktif', default=True)

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu harici mal grubu zaten tanımlı.',
    )
