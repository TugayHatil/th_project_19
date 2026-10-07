# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class PurchaseOrderRejectWizard(models.TransientModel):
    _name = 'purchase.order.reject.wizard'
    _description = 'Purchase Order Reject Wizard'

    order_id = fields.Many2one(
        'purchase.order', string='Satınalma Siparişi', required=True,
        readonly=True)
    reject_reason_id = fields.Many2one(
        'purchase.order.reject.reason', string='Red Nedeni',
        required=True, domain="[('active', '=', True)]")

    def action_reject(self):
        self.ensure_one()
        if not self.reject_reason_id:
            raise UserError(_(
                'Siparişi reddetmek için red nedeni seçmeniz '
                'gerekmektedir.'))
        self.order_id._do_reject(self.reject_reason_id.name)
        return {'type': 'ir.actions.act_window_close'}
