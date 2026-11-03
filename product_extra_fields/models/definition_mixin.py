# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductExtraDefinitionMixin(models.AbstractModel):
    _name = 'product.extra.definition.mixin'
    _description = 'Ürün Ek Alan Tanım Modeli Temel Sınıfı'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(string='Aktif', default=True)

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
