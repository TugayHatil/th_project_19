# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductionSupervisor(models.Model):
    _name = 'production.supervisor'
    _description = 'Üretim Sorumlusu'
    _order = 'name'

    name = fields.Char(string='Üretim Sorumlusu No', required=True)
    responsible = fields.Char(string='Üretim Sorumlusu')
    active = fields.Boolean(string='Aktif', default=True)

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu Üretim Sorumlusu No zaten tanımlı.',
    )
