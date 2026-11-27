# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    expected_loading_date = fields.Datetime(
        string='Beklenen Yükleme', compute='_compute_expected_loading_date',
        store=True, readonly=False, copy=False)

    @api.depends('date_planned', 'order_id.shipping_type', 'selected_seller_id')
    def _compute_expected_loading_date(self):
        for line in self:
            shipping_type = line.order_id.shipping_type
            if not line.date_planned:
                line.expected_loading_date = False
            elif shipping_type:
                line.expected_loading_date = line.date_planned - timedelta(
                    days=line._get_shipping_days(shipping_type))

    def _get_shipping_days(self, shipping_type):
        """Seçili sevk türü için tedarikçi fiyat satırındaki transit süre (gün)."""
        self.ensure_one()
        delay = self.selected_seller_id.shipping_delay_ids.filtered(
            lambda d: d.shipping_type == shipping_type)
        return delay.days if delay else 0
