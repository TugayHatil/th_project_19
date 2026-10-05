# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_manufacturer = fields.Boolean(
        string='Üretici mi?',
        default=False,
    )
