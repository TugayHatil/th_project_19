# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    to_transfer = fields.Boolean(
        string='Aktar',
        default=False,
        copy=False,
        help="Kesin siparişe aktarılacak satırı işaretler.")
    transfer_qty = fields.Float(
        string='Aktarım',
        digits='Product Unit of Measure',
        default=0.0,
        copy=False,
        help="Kesin siparişe aktarılacak miktar. Boş/0 bırakılırsa satır "
             "miktarının tamamı aktarılır ve satır silinir.")
    forecast_source_line_id = fields.Many2one(
        'sale.order.line',
        string='Kaynak Öngörü Satırı',
        copy=False,
        readonly=True,
        index=True,
        ondelete='set null',
        help="Bu satırın aktarıldığı Öngörü siparişi satırı.")

    @api.onchange('to_transfer', 'product_uom_qty')
    def _onchange_to_transfer(self):
        for line in self:
            line.transfer_qty = (
                line.product_uom_qty if line.to_transfer else 0.0)

    @api.constrains('transfer_qty', 'product_uom_qty')
    def _check_transfer_qty(self):
        for line in self:
            precision = line.product_uom_id.rounding or 0.01
            if float_compare(line.transfer_qty, 0.0,
                             precision_rounding=precision) < 0:
                raise ValidationError(_(
                    "Aktarım miktarı negatif olamaz."))
            if float_compare(line.transfer_qty, line.product_uom_qty,
                             precision_rounding=precision) > 0:
                raise ValidationError(_(
                    "Aktarım miktarı (%(qty)s), \"%(product)s\" satırının "
                    "sipariş miktarından (%(ordered)s) büyük olamaz.",
                    qty=line.transfer_qty,
                    product=line.product_id.display_name,
                    ordered=line.product_uom_qty))

    def _action_launch_stock_rule(self, *, previous_product_uom_qty=False):
        """ Öngörü niteliğindeki siparişlerin satırları için tedarik/stok
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
