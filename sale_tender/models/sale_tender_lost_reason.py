# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleTenderLostReason(models.Model):
    _name = 'sale.tender.lost.reason'
    _description = 'İhale Kayıt Nedeni'
    _order = 'sequence, id'

    name = fields.Char(string='Kayıt Nedeni', required=True, translate=True)
    sequence = fields.Integer(string='Sıra', default=10)
    active = fields.Boolean(string='Aktif', default=True)
