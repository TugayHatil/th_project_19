# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .product_supplierinfo_shipping_delay import SHIPPING_TYPES


class ProductSupplierinfo(models.Model):
    _inherit = 'product.supplierinfo'

    shipping_delay_ids = fields.One2many(
        'product.supplierinfo.shipping.delay', 'supplierinfo_id',
        string='Sevk Süreleri', copy=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_shipping_delay_lines()
        return records

    def _ensure_shipping_delay_lines(self):
        """Eksik sevk türleri için süre satırları oluşturur."""
        Delay = self.env['product.supplierinfo.shipping.delay']
        vals_list = []
        for supplierinfo in self:
            existing = set(supplierinfo.shipping_delay_ids.mapped('shipping_type'))
            vals_list += [
                {'supplierinfo_id': supplierinfo.id, 'shipping_type': shipping_type}
                for shipping_type, _label in SHIPPING_TYPES if shipping_type not in existing
            ]
        if vals_list:
            Delay.create(vals_list)

    def action_open_supplierinfo(self):
        """Ürün kartındaki editable listeden fiyat satırı formunu dialog olarak aç."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.supplierinfo',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _recompute_po_loading_dates(self):
        """Sevk süresi değişiminde ilgili taslak sipariş satırlarını yeniden hesaplat."""
        products = self.product_id | self.product_tmpl_id.product_variant_ids
        partners = self.partner_id.commercial_partner_id
        lines = self.env['purchase.order.line'].search([
            ('product_id', 'in', products.ids),
            ('order_id.state', 'in', ['draft', 'sent', 'to approve']),
            ('order_id.partner_id', 'child_of', partners.ids),
            ('order_id.shipping_type', '!=', False),
        ])
        lines._compute_expected_loading_date()
