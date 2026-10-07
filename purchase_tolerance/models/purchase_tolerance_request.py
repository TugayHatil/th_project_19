# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseToleranceRequest(models.Model):
    _name = 'purchase.tolerance.request'
    _description = 'Purchase Tolerance Over-Delivery Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Talep No', required=True, readonly=True, copy=False,
        default=lambda self: _('Yeni'))
    state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
        ('cancel', 'İptal'),
    ], string='Durum', default='pending', required=True, tracking=True, copy=False)

    order_id = fields.Many2one(
        'purchase.order', string='Satınalma Siparişi', required=True,
        readonly=True, index=True, check_company=True)
    order_line_id = fields.Many2one(
        'purchase.order.line', string='PO Satırı', required=True,
        readonly=True, index=True, ondelete='cascade', check_company=True)
    product_id = fields.Many2one(
        related='order_line_id.product_id', string='Ürün', store=True)
    uom_id = fields.Many2one(
        related='order_line_id.product_uom_id', string='Birim')
    picking_id = fields.Many2one('stock.picking', string='Mal Kabul', readonly=True)
    company_id = fields.Many2one(
        related='order_id.company_id', string='Şirket', store=True)

    ordered_qty = fields.Float(
        string='Sipariş Miktarı', digits='Product Unit', readonly=True)
    received_qty = fields.Float(
        string='Önceki Kabul Edilen Miktar', digits='Product Unit', readonly=True)
    incoming_qty = fields.Float(
        string='Gelen / Kabul Edilmek İstenen Miktar',
        digits='Product Unit', readonly=True)
    current_tolerance = fields.Float(
        string='Mevcut Tolerans (%)', digits='Discount', readonly=True)
    max_accepted_qty = fields.Float(
        string='Maks. Kabul Edilebilir Miktar', digits='Product Unit',
        compute='_compute_max_accepted_qty')
    requested_tolerance = fields.Float(
        string='Talep Edilen Tolerans (%)', digits='Discount', readonly=True)

    user_id = fields.Many2one(
        'res.users', string='Talep Eden', required=True, readonly=True,
        default=lambda self: self.env.user)
    request_date = fields.Datetime(
        string='Talep Tarihi', readonly=True, default=fields.Datetime.now)
    approver_id = fields.Many2one(
        'res.users', string='Onaylayan', readonly=True, copy=False)
    approve_date = fields.Datetime(string='Onay Tarihi', readonly=True, copy=False)
    reject_reason = fields.Text(string='Red Nedeni', tracking=True)

    @api.depends('ordered_qty', 'current_tolerance')
    def _compute_max_accepted_qty(self):
        for request in self:
            request.max_accepted_qty = \
                request.ordered_qty * (1 + request.current_tolerance / 100.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Yeni')) == _('Yeni'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'purchase.tolerance.request') or _('Yeni')
        return super().create(vals_list)

    def _check_manager(self):
        if not self.env.user.has_group('purchase.group_purchase_manager'):
            raise UserError(_(
                'Bu işlem yalnızca Satınalma Yöneticisi tarafından yapılabilir.'))

    def _schedule_review_activity(self):
        for request in self:
            assignee = request.order_id.user_id
            if not assignee:
                assignee = self.env.ref('purchase.group_purchase_manager').users[:1] \
                    or self.env.user
            request.activity_schedule(
                'purchase_tolerance.mail_activity_type_tolerance_request',
                user_id=assignee.id,
                summary=_('Tolerans Aşımı Talebini İncele'),
                note=_(
                    '%(po)s siparişinde %(product)s ürünü için satınalma '
                    'toleransı aşıldı. Talep edilen tolerans: %(tol)s%%',
                    po=request.order_id.name,
                    product=request.product_id.display_name,
                    tol=request.requested_tolerance,
                ),
            )

    def action_approve(self):
        self._check_manager()
        for request in self.filtered(lambda r: r.state == 'pending'):
            request.order_line_id.write(
                {'purchase_tolerance': request.requested_tolerance})
            request.write({
                'state': 'approved',
                'approver_id': self.env.user.id,
                'approve_date': fields.Datetime.now(),
            })
            request.activity_ids.action_done(feedback=_('Talep onaylandı.'))
            request.order_id.message_post(body=_(
                '%(name)s numaralı tolerans aşımı talebi onaylandı. '
                'PO satırı toleransı %(tol)s%% olarak güncellendi.',
                name=request.name, tol=request.requested_tolerance))
        return True

    def action_reject(self):
        self._check_manager()
        for request in self.filtered(lambda r: r.state == 'pending'):
            request.write({
                'state': 'rejected',
                'approver_id': self.env.user.id,
                'approve_date': fields.Datetime.now(),
            })
            request.activity_ids.action_done(feedback=_('Talep reddedildi.'))
            request.order_id.message_post(body=_(
                '%(name)s numaralı tolerans aşımı talebi reddedildi.',
                name=request.name))
        return True

    def action_cancel(self):
        for request in self.filtered(lambda r: r.state == 'pending'):
            if not self.env.user.has_group('purchase.group_purchase_manager') \
                    and request.user_id != self.env.user:
                raise UserError(_(
                    'Yalnızca talebi oluşturan kullanıcı veya Satınalma '
                    'Yöneticisi talebi iptal edebilir.'))
            request.state = 'cancel'
            request.activity_ids.action_done(feedback=_('Talep iptal edildi.'))
        return True
