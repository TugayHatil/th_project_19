# -*- coding: utf-8 -*-
from odoo import models, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _action_launch_stock_rule(self, *, previous_product_uom_qty=False):
        """ Forecast niteliğindeki siparişlerin satırları için tedarik/stok
        kuralı çalıştırılmaz; böylece onay veya satır güncellemesi sırasında
        teslimat emri, rezervasyon ve stok hareketi oluşmaz."""
        lines = self.filtered(lambda l: l.order_id.order_nature != 'forecast')
        if not lines:
            return True
        return super(SaleOrderLine, lines)._action_launch_stock_rule(
            previous_product_uom_qty=previous_product_uom_qty)

    @api.depends('order_id.order_nature')
    def _compute_qty_to_invoice(self):
        super()._compute_qty_to_invoice()
        for line in self.filtered(lambda l: l.order_id.order_nature == 'forecast'):
            line.qty_to_invoice = 0
