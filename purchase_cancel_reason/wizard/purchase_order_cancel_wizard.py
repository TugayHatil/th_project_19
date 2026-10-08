# -*- coding: utf-8 -*-
from markupsafe import escape

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_datetime

MIN_DESCRIPTION_LENGTH = 10


class PurchaseOrderCancelWizard(models.TransientModel):
    _name = 'purchase.order.cancel.wizard'
    _description = 'Purchase Order Cancel Wizard'

    order_ids = fields.Many2many(
        'purchase.order', string='Satınalma Siparişleri',
        required=True, readonly=True)
    cancel_reason_id = fields.Many2one(
        'purchase.order.cancel.reason', string='İptal Nedeni',
        required=True, domain="[('active', '=', True)]")
    reason_is_other = fields.Boolean(
        related='cancel_reason_id.is_other')
    description = fields.Text(string='Açıklama')

    def action_confirm_cancel(self):
        self.ensure_one()
        if not self.cancel_reason_id:
            raise UserError(_(
                'Siparişi iptal etmek için iptal nedeni seçmeniz '
                'gerekmektedir.'))
        description = (self.description or '').strip()
        if self.reason_is_other and not description:
            raise UserError(_(
                '"Diğer" iptal nedeni seçildiğinde açıklama girilmesi '
                'zorunludur.'))
        if description and len(description) < MIN_DESCRIPTION_LENGTH:
            raise UserError(_(
                'Açıklama en az %(length)d karakter olmalıdır.',
                length=MIN_DESCRIPTION_LENGTH))

        # Popup açıldıktan sonra durumu değişen kayıtları ele
        # (selection'a yazılamaz / gereksiz iptal olmasın)
        orders = self.order_ids.filtered(
            lambda o: o.state in ('sent', 'to approve', 'purchase'))
        if not orders:
            raise UserError(_(
                'Siparişin durumu değişti; iptal işlemi uygulanamadı.'))

        # İptal anındaki aşamaları iptalden önce yakala
        cancel_states = {order.id: order.state for order in orders}
        orders.button_cancel()

        cancel_date = fields.Datetime.now()
        state_labels = dict(
            self.env['purchase.order']._fields['cancel_state']
                ._description_selection(self.env))
        for order in orders:
            order.write({
                'cancel_reason_id': self.cancel_reason_id.id,
                'cancel_description': description or False,
                'cancel_state': cancel_states[order.id],
                'cancel_user_id': self.env.user.id,
                'cancel_date': cancel_date,
            })
            order.message_post(body=_(
                'Satınalma siparişi iptal edildi.<br/>'
                '<strong>İptal Nedeni:</strong> %(reason)s<br/>'
                '<strong>İptal Edildiği Aşama:</strong> %(state)s<br/>'
                '<strong>İptal Eden:</strong> %(user)s<br/>'
                '<strong>İptal Tarihi:</strong> %(date)s<br/>'
                '<strong>Açıklama:</strong> %(description)s',
                reason=escape(str(self.cancel_reason_id.display_name)),
                state=escape(str(state_labels.get(
                    order.cancel_state, order.cancel_state or ''))),
                user=escape(str(self.env.user.display_name)),
                date=format_datetime(
                    self.env, cancel_date, dt_format='short'),
                description=escape(description) if description else '-'))
        return {'type': 'ir.actions.act_window_close'}
