# -*- coding: utf-8 -*-
from odoo import models


class LunaHardwareVersion(models.Model):
    _name = 'luna.hardware.version'
    _description = 'Donanım Versiyonu'
    _inherit = 'luna.helpdesk.definition'

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu donanım versiyonu zaten tanımlı.',
    )
