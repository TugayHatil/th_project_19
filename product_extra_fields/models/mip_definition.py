# -*- coding: utf-8 -*-
from odoo import fields, models


class MipDefinition(models.Model):
    _name = 'mip.definition'
    _description = 'MİP Tanımı'
    _inherit = 'product.extra.definition.mixin'

    name = fields.Char(string='MİP No')
    responsible = fields.Char(string='MİP Sorumlusu')

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu MİP No zaten tanımlı.',
    )
