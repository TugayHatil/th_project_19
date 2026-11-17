# -*- coding: utf-8 -*-
from odoo import models


class LunaNoticedLocation(models.Model):
    _name = 'luna.noticed.location'
    _description = 'Farkedildiği Yer'
    _inherit = 'luna.helpdesk.definition'

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu farkedildiği yer zaten tanımlı.',
    )
