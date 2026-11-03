# -*- coding: utf-8 -*-
from odoo import fields, models


class MipDefinition(models.Model):
    _name = 'mip.definition'
    _description = 'MİP Tanımı'
    _order = 'name'

    name = fields.Char(string='MİP No', required=True)
    responsible_id = fields.Many2one(
        'hr.employee', string='MİP Sorumlusu', ondelete='restrict')
    active = fields.Boolean(string='Aktif', default=True)

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu MİP No zaten tanımlı.',
    )
