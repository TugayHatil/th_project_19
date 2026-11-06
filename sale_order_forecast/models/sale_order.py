# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError
from odoo.tools import format_datetime


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    order_nature = fields.Selection(
        selection=[
            ('normal', 'Kesin'),
            ('forecast', 'Öngörü'),
        ],
        string='Sipariş Niteliği',
        required=True,
        default='normal',
        tracking=True,
        help="Kesin: standart satış siparişi süreci.\n"
             "Öngörü: teslimat emri oluşturulmadan onaylanabilen satış siparişi.")
    forecast_converted = fields.Boolean(
        string='Öngörü\'den Dönüştürüldü',
        default=False,
        copy=False,
        readonly=True,
        help="Bu sipariş Öngörü niteliğinden Kesin niteliğe dönüştürülmüştür. "
             "Dönüştürme tek yönlüdür ve tekrarlanamaz.")

    def write(self, vals):
        if 'order_nature' in vals and not self.env.context.get('order_nature_change_allowed'):
            for order in self:
                if vals['order_nature'] == order.order_nature:
                    continue
                if order.forecast_converted and vals['order_nature'] == 'forecast':
                    raise UserError(_(
                        "Dönüştürülmüş bir sipariş tekrar Öngörü niteliğine alınamaz."))
                if order.state not in ('draft', 'sent'):
                    raise UserError(_(
                        "Onaylanmış veya iptal edilmiş bir siparişin niteliği değiştirilemez. "
                        "Öngörü siparişleri yalnızca \"Kesin Siparişe Dönüştür\" "
                        "butonu ile Kesin niteliğe çevrilebilir."))
        return super().write(vals)

    def action_convert_to_normal(self):
        for order in self:
            if order.order_nature != 'forecast':
                raise UserError(_(
                    "Yalnızca Öngörü niteliğindeki siparişler Kesin siparişe "
                    "dönüştürülebilir."))
            if order.state != 'sale':
                raise UserError(_(
                    "Yalnızca onaylanmış (Satış Siparişi) Öngörü siparişleri "
                    "dönüştürülebilir."))
            order._convert_forecast_to_normal()
        return True

    def _convert_forecast_to_normal(self):
        """ Öngörü siparişini Kesin niteliğe çevirir ve standart stok/tedarik
        kuralı mekanizmasını çalıştırarak teslimat emrini oluşturur.

        Tüm işlem tek transaction içinde yürür; herhangi bir adım hata verirse
        nitelik değişikliği dahil her şey geri alınır.
        """
        self.ensure_one()
        # Daha önce stok hareketi oluşmuş satırları atlayarak mükerrer teslimatı engelle.
        lines = self.order_line.filtered(
            lambda l: l.state == 'sale' and not l.move_ids.filtered(
                lambda m: m.state != 'cancel'))
        if not lines:
            raise UserError(_(
                "Dönüştürülecek teslimat satırı bulunamadı. Siparişin stok "
                "hareketleri zaten oluşturulmuş olabilir."))
        was_locked = self.locked
        if was_locked:
            # Kilitli siparişler _action_launch_stock_rule tarafından atlanır;
            # kural çalıştırılırken kilidi geçici olarak kaldır.
            self.locked = False
        self.with_context(order_nature_change_allowed=True).write({
            'order_nature': 'normal',
            'forecast_converted': True,
        })
        try:
            lines._action_launch_stock_rule()
        finally:
            if was_locked:
                self.locked = True
        self.message_post(body=_(
            "Öngörü siparişi Kesin siparişe dönüştürüldü. "
            "İşlemi yapan: %(user)s – Tarih: %(date)s",
            user=self.env.user.display_name,
            date=format_datetime(self.env, fields.Datetime.now())))

    def _create_invoices(self, grouped=False, final=False, date=None):
        forecast_orders = self.filtered(lambda o: o.order_nature == 'forecast')
        if forecast_orders:
            raise UserError(_(
                "Öngörü niteliğindeki siparişlerden fatura oluşturulamaz. "
                "Önce siparişi Kesin niteliğe dönüştürün. (%s)",
                ', '.join(forecast_orders.mapped('name'))))
        return super()._create_invoices(grouped=grouped, final=final, date=date)
