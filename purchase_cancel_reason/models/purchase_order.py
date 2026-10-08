# -*- coding: utf-8 -*-
from odoo import Command, fields, models

# İptal nedeni istenen durumlar; draft ve kilitli (Done) siparişler
# popup açmadan standart akışıyla iptal edilir.
REASON_REQUIRED_STATES = ('sent', 'to approve', 'purchase')


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    cancel_reason_id = fields.Many2one(
        'purchase.order.cancel.reason', string='İptal Nedeni',
        readonly=True, copy=False)
    cancel_reason_is_other = fields.Boolean(
        string='"Diğer" İptal Nedeni',
        related='cancel_reason_id.is_other', store=True)
    cancel_description = fields.Text(
        string='İptal Açıklaması', readonly=True, copy=False)
    cancel_state = fields.Selection([
        ('sent', 'RFQ Gönderildi'),
        ('to approve', 'Onay Bekliyor'),
        ('purchase', 'Satınalma Siparişi'),
    ], string='İptal Edildiği Aşama', readonly=True, copy=False)
    cancel_user_id = fields.Many2one(
        'res.users', string='İptal Eden', readonly=True, copy=False)
    cancel_date = fields.Datetime(
        string='İptal Tarihi', readonly=True, copy=False)

    # ------------------------------------------------------------
    # İptal akışı
    # ------------------------------------------------------------

    def action_cancel_orders(self):
        """UI tarafı ortak girişi (formdaki ve listedeki İptal Et
        butonları burayı çağırır): neden gerekmeyen kayıtlar standart
        button_cancel ile iptal edilir; neden gerekenler İptal Nedeni
        wizard'ı açar, wizard onaylayınca button_cancel çağrılır.
        button_cancel'in kendisi override edilmez — iç akışlar
        (RFQ birleştirme vb.) popup açmadan çalışmaya devam eder."""
        reason_required = self.filtered(
            lambda o: o.state in REASON_REQUIRED_STATES and not o.locked)
        (self - reason_required).button_cancel()
        if reason_required:
            return reason_required.action_open_cancel_reason_wizard()
        return True

    def action_open_cancel_reason_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('İptal Nedeni'),
            'res_model': 'purchase.order.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_order_ids': [Command.set(self.ids)],
            },
        }

    def button_draft(self):
        """İptalden taslağa dönen siparişin eski iptal bilgilerini
        temizler; böylece İptal Analizi raporuna eski kayıtlar
        girmez."""
        res = super().button_draft()
        self.filtered('cancel_reason_id').write({
            'cancel_reason_id': False,
            'cancel_description': False,
            'cancel_state': False,
            'cancel_user_id': False,
            'cancel_date': False,
        })
        return res
