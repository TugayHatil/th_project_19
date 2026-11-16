# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ProductExtraDefinitionMixin(models.AbstractModel):
    _name = 'product.extra.definition.mixin'
    _description = 'Ürün Ek Alan Tanım Modeli Temel Sınıfı'
    _order = 'name'

    # product.template üzerinde bu tanıma işaret eden alanın adı;
    # ürün sayacı ve smartbuton için kullanılır.
    _product_field_name = None

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

    def _compute_product_count(self):
        for rec in self:
            rec.product_count = self.env['product.template'].search_count(
                [(self._product_field_name, '=', rec.id)])

    def action_view_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ürünler'),
            'res_model': 'product.template',
            'view_mode': 'kanban,list,form',
            'domain': [(self._product_field_name, '=', self.id)],
            'context': {'default_%s' % self._product_field_name: self.id},
        }
