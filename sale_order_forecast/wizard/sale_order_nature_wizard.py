# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class SaleOrderNatureWizard(models.TransientModel):
    _name = 'sale.order.nature.wizard'
    _description = 'Sipariş Niteliği Seçim Sihirbazı'

    order_id = fields.Many2one(
        'sale.order', string='Satış Siparişi', required=True, readonly=True)

    def action_select_confirmed(self):
        return self._select_nature('confirmed')

    def action_select_forecast(self):
        return self._select_nature('forecast')

    def _select_nature(self, nature):
        """ Nitelik yazılır ve standart onay süreci çalıştırılır. Onaylama
        başarısız olursa tüm işlem (nitelik yazımı dahil) aynı transaction
        içinde geri alınır."""
        self.ensure_one()
        order = self.order_id
        if order.state not in ('draft', 'sent'):
            raise UserError(_(
                "Sipariş artık onaylanabilir durumda değil."))
        if order.order_nature:
            raise UserError(_(
                "Sipariş niteliği zaten belirlenmiş."))
        order.write({'order_nature': nature})
        return order.action_confirm()
