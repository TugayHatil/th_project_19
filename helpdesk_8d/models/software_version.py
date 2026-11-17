# -*- coding: utf-8 -*-
from odoo import models


class LunaSoftwareVersion(models.Model):
    _name = 'luna.software.version'
    _description = 'Yazılım Versiyonu'
    _inherit = 'luna.helpdesk.definition'

    _name_unique = models.Constraint(
        'unique(name)',
        'Bu yazılım versiyonu zaten tanımlı.',
    )
