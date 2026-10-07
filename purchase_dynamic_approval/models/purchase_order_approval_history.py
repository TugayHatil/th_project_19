# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrderApprovalHistory(models.Model):
    _name = 'purchase.order.approval.history'
    _description = 'Purchase Order Approval History'
    _order = 'date, id'
    _check_company_auto = True

    order_id = fields.Many2one(
        'purchase.order', string='Satınalma Siparişi', required=True,
        readonly=True, index=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(
        related='order_id.company_id', string='Şirket', store=True,
        readonly=True)
    date = fields.Datetime(string='Tarih', required=True, readonly=True)
    action = fields.Selection([
        ('submit', 'Onaya Gönderildi'),
        ('approve', 'Onaylandı'),
        ('reject', 'Reddedildi'),
        ('tier_change', 'Barem Değişti'),
        ('amount_change', 'Tutar Değişti'),
        ('auto_approve', 'Otomatik Onaylandı'),
        ('reset', 'Taslağa Alındı'),
        ('cancel', 'İptal Edildi'),
    ], string='İşlem', required=True, readonly=True)
    tier_id = fields.Many2one(
        'purchase.approval.tier', string='Onay Baremı', readonly=True,
        check_company=True)
    approval_group_id = fields.Many2one(
        'res.groups', string='Onaylayıcı Grup', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Kullanıcı', readonly=True)
    amount_total = fields.Monetary(
        string='Toplam Tutar', readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        related='order_id.currency_id', store=True, readonly=True)
    note = fields.Text(string='Açıklama', readonly=True)
