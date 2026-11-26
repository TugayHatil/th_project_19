# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductionSupervisor(models.Model):
    _name = 'production.supervisor'
    _description = 'Üretim Sorumlusu'
    _inherit = 'product.extra.definition.mixin'

    name = fields.Char(string='Üretim Sorumlusu No')
    responsible = fields.Char(string='Üretim Sorumlusu')

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu Üretim Sorumlusu No zaten tanımlı.',
    )
