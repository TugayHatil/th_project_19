# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LunaHelpdeskDefinition(models.AbstractModel):
    _name = 'luna.helpdesk.definition'
    _description = 'Luna Helpdesk Tanım Temel Sınıfı'
    _order = 'name'

    name = fields.Char(required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name'):
                vals['name'] = vals['name'].strip()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('name'):
            vals['name'] = vals['name'].strip()
        return super().write(vals)
