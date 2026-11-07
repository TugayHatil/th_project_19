# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleTenderCompetitor(models.Model):
    _name = 'sale.tender.competitor'
    _description = 'İhale Rakibi'
    _order = 'name'

    name = fields.Char(string='Rakip', required=True)
    color = fields.Integer(string='Renk')
