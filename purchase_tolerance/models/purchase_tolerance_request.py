# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class PurchaseToleranceRequest(models.Model):
    _name = 'purchase.tolerance.request'
    _description = 'Satınalma Tolerans Fazla Teslimat Talebi'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Talep No', required=True, readonly=True, copy=False,
        default=lambda self: _('Yeni'))
    state = fields.Selection([
        ('pending', 'Bekliyor'),
        ('approved', 'Onaylandı'),
        ('conditional', 'Koşullu'),
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
    move_ids = fields.Many2many(
        'stock.move', 'purchase_tolerance_request_move_rel',
        'request_id', 'move_id', string='Transfer Satırları', readonly=True)
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
    excess_qty = fields.Float(
        string='Tolerans Dışı Miktar', digits='Product Unit',
        compute='_compute_max_accepted_qty')
    requested_tolerance = fields.Float(
        string='Talep Edilen Tolerans (%)', digits='Discount', readonly=True)
    approved_tolerance = fields.Float(
        string='Onaylanan Tolerans (%)', digits='Discount',
        help="Talep edilenden düşük girilirse talep Koşullu onaylanır; "
             "onaylanan kısmın üzerindeki miktar tolerans dışı konuma "
             "yönlendirilir ve iade transferi oluşturulur.")
    approved_qty = fields.Float(
        string='Onaylanan Miktar', digits='Product Unit',
        compute='_compute_approved_quantities')
    return_qty = fields.Float(
        string='İade Edilecek Miktar', digits='Product Unit',
        compute='_compute_approved_quantities')
    return_picking_id = fields.Many2one(
        'stock.picking', string='İade Transferi', readonly=True, copy=False)

    user_id = fields.Many2one(
        'res.users', string='Talep Eden', required=True, readonly=True,
        default=lambda self: self.env.user)
    request_date = fields.Datetime(
        string='Talep Tarihi', readonly=True, default=fields.Datetime.now)
    responsible_id = fields.Many2one(
        'res.users', string='Yönlendirilen Satınalma Sorumlusu',
        readonly=True, copy=False)
    approver_id = fields.Many2one(
        'res.users', string='Onaylayan', readonly=True, copy=False)
    approve_date = fields.Datetime(string='Onay Tarihi', readonly=True, copy=False)
    reject_reason = fields.Text(string='Red Nedeni', tracking=True)

    @api.depends('ordered_qty', 'current_tolerance',
                 'received_qty', 'incoming_qty')
    def _compute_max_accepted_qty(self):
        for request in self:
            request.max_accepted_qty = \
                request.ordered_qty * (1 + request.current_tolerance / 100.0)
            request.excess_qty = max(
                request.received_qty + request.incoming_qty
                - request.max_accepted_qty, 0.0)

    @api.depends('ordered_qty', 'approved_tolerance',
                 'received_qty', 'incoming_qty')
    def _compute_approved_quantities(self):
        for request in self:
            approved = request.ordered_qty * (
                1 + request.approved_tolerance / 100.0)
            request.approved_qty = approved
            request.return_qty = max(
                request.received_qty + request.incoming_qty - approved, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Yeni')) == _('Yeni'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'purchase.tolerance.request') or _('Yeni')
            vals.setdefault('approved_tolerance',
                            vals.get('requested_tolerance'))
        return super().create(vals_list)

    @api.constrains('requested_tolerance', 'approved_tolerance')
    def _check_tolerances(self):
        for request in self:
            if request.requested_tolerance < 0 \
                    or request.approved_tolerance < 0:
                raise ValidationError(_('Tolerans oranı negatif olamaz.'))

    def _check_manager(self):
        if not self.env.user.has_group('purchase.group_purchase_manager'):
            raise UserError(_(
                'Bu işlem yalnızca Satınalma Yöneticisi tarafından yapılabilir.'))

    def _schedule_review_activity(self):
        for request in self:
            assignee = request.order_id.user_id
            if not assignee:
                assignee = self.env.ref('purchase.group_purchase_manager') \
                    .all_user_ids.filtered('active')[:1] or self.env.user
            request.sudo().responsible_id = assignee
            request.activity_schedule(
                'purchase_tolerance.mail_activity_type_tolerance_request',
                user_id=assignee.id,
                summary=_('Tolerans Aşımı Talebini İncele'),
                note=_(
                    '%(po)s siparişinde %(product)s ürünü için satınalma '
                    'toleransı aşıldı. Sipariş: %(ordered)s %(uom)s, '
                    'girilen miktar: %(qty)s %(uom)s, mevcut tolerans: '
                    '%(cur)s%%, talep edilen tolerans: %(tol)s%%.',
                    po=request.order_id.name,
                    product=request.product_id.display_name,
                    ordered=request.ordered_qty,
                    uom=request.uom_id.name or '',
                    qty=request.received_qty + request.incoming_qty,
                    cur=request.current_tolerance,
                    tol=request.requested_tolerance,
                ),
            )

    def _get_decision_message(self, decision):
        """Karar bilgisini transfer chatter'ına yazılacak formatta üret."""
        self.ensure_one()
        lines = [
            _('Tolerans talebi %(decision)s. (%(name)s)',
              decision=decision, name=self.name),
            _('Ürün: %s', self.product_id.display_name),
            _('Sipariş miktarı: %(qty)s %(uom)s',
              qty=self.ordered_qty, uom=self.uom_id.name or ''),
            _('Girilen miktar: %(qty)s %(uom)s',
              qty=self.received_qty + self.incoming_qty,
              uom=self.uom_id.name or ''),
            _('Tolerans: %(tol)s%%', tol=self.current_tolerance),
        ]
        if decision == 'koşullu onaylandı':
            lines.append(_(
                'Onaylanan tolerans: %(tol)s%%', tol=self.approved_tolerance))
            lines.append(_(
                'Onaylanan miktar: %(qty)s %(uom)s',
                qty=self.approved_qty, uom=self.uom_id.name or ''))
            lines.append(_(
                'İade edilecek miktar: %(qty)s %(uom)s',
                qty=self.return_qty, uom=self.uom_id.name or ''))
            if self.return_picking_id:
                lines.append(_(
                    'İade konumu: %s',
                    self.return_picking_id.location_id.display_name))
                lines.append(_(
                    'İade transferi: %s',
                    self.return_picking_id._get_html_link()))
        if decision == 'reddedildi':
            lines.append(_('Reddeden: %s', self.approver_id.name or ''))
        else:
            lines.append(_('Onaylayan: %s', self.approver_id.name or ''))
        decision_dt = self.approve_date or fields.Datetime.now()
        lines.append(_('Karar tarihi: %s', fields.Datetime.context_timestamp(
            self, decision_dt).strftime('%d.%m.%Y %H:%M')))
        if decision == 'reddedildi' and self.reject_reason:
            lines.append(_('Açıklama: %s', self.reject_reason))
        # Düz str gövde message_post'ta escape edilir; satırlar escape
        # edilerek Markup ile birleştirilir.
        return Markup('<br/>').join(lines)

    def action_approve(self):
        self._check_manager()
        for request in self.filtered(lambda r: r.state == 'pending'):
            approved = request.approved_tolerance \
                if request.approved_tolerance else request.requested_tolerance
            is_conditional = float_compare(
                approved, request.requested_tolerance,
                precision_digits=2) < 0
            request.order_line_id.with_context(
                skip_tolerance_change_log=True).write(
                {'purchase_tolerance': approved})
            request.write({
                'state': 'conditional' if is_conditional else 'approved',
                'approver_id': self.env.user.id,
                'approve_date': fields.Datetime.now(),
            })
            if is_conditional:
                request._create_return_picking()
                request.activity_ids.action_feedback(
                    feedback=_('Talep koşullu onaylandı.'))
                request.order_id.message_post(body=_(
                    '%(name)s numaralı tolerans aşımı talebi koşullu '
                    'onaylandı. PO satırı toleransı %(tol)s%% olarak '
                    'güncellendi; %(qty)s %(uom)s tolerans dışı miktar '
                    'iade edilecek.',
                    name=request.name, tol=approved,
                    qty=request.return_qty,
                    uom=request.uom_id.name or ''))
                if request.picking_id:
                    request.picking_id.sudo().message_post(
                        body=request._get_decision_message(
                            'koşullu onaylandı'),
                        message_type='comment')
            else:
                request.activity_ids.action_feedback(
                    feedback=_('Talep onaylandı.'))
                request.order_id.message_post(body=_(
                    '%(name)s numaralı tolerans aşımı talebi onaylandı. '
                    'PO satırı toleransı %(tol)s%% olarak güncellendi.',
                    name=request.name, tol=approved))
                if request.picking_id:
                    request.picking_id.sudo().message_post(
                        body=request._get_decision_message('onaylandı'),
                        message_type='comment')
        return True

    def _create_return_picking(self):
        """Onaylanan miktarın üzerindeki tolerans dışı miktar için
        tolerans dışı konumdan tedarikçiye iade transferi oluşturur."""
        self.ensure_one()
        if self.return_picking_id or self.return_qty <= 0:
            return self.return_picking_id
        receipt = self.picking_id
        excess_loc = receipt._get_tolerance_excess_location()
        warehouse = receipt.picking_type_id.warehouse_id
        out_type = warehouse.out_type_id if warehouse else False
        if not out_type:
            out_type = self.env['stock.picking.type'].sudo().search([
                ('code', '=', 'outgoing'),
                ('company_id', '=', receipt.company_id.id),
            ], limit=1)
        if not out_type:
            raise UserError(_(
                'İade transferi için uygun çıkış operasyon tipi bulunamadı.'))
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': out_type.id,
            'location_id': excess_loc.id,
            'location_dest_id': receipt.location_id.id,
            'partner_id': receipt.partner_id.id,
            'origin': '%s / %s' % (receipt.name, self.name),
            'company_id': receipt.company_id.id,
            'tolerance_origin_picking_id': receipt.id,
            'move_ids': [(0, 0, {
                'name': self.product_id.display_name,
                'product_id': self.product_id.id,
                'product_uom_qty': self.return_qty,
                'product_uom': self.uom_id.id,
                'location_id': excess_loc.id,
                'location_dest_id': receipt.location_id.id,
                'purchase_line_id': self.order_line_id.id,
                'company_id': receipt.company_id.id,
            })],
        })
        picking.action_confirm()
        self.return_picking_id = picking
        return picking

    def action_reject(self):
        self._check_manager()
        for request in self.filtered(lambda r: r.state == 'pending'):
            if not request.reject_reason:
                raise UserError(_(
                    'Talebi reddetmek için red nedeni girmeniz gerekmektedir.'))
            request.write({
                'state': 'rejected',
                'approver_id': self.env.user.id,
                'approve_date': fields.Datetime.now(),
            })
            request.activity_ids.action_feedback(feedback=_('Talep reddedildi.'))
            request.order_id.message_post(body=_(
                '%(name)s numaralı tolerans aşımı talebi reddedildi. '
                'Red nedeni: %(reason)s',
                name=request.name, reason=request.reject_reason))
            if request.picking_id:
                request.picking_id.sudo().message_post(
                    body=request._get_decision_message('reddedildi'),
                    message_type='comment')
        return True

    def action_cancel(self):
        for request in self.filtered(lambda r: r.state == 'pending'):
            if not self.env.user.has_group('purchase.group_purchase_manager') \
                    and request.user_id != self.env.user:
                raise UserError(_(
                    'Yalnızca talebi oluşturan kullanıcı veya Satınalma '
                    'Yöneticisi talebi iptal edebilir.'))
            # Talep sahibinin request üzerinde write hakkı yok; iptal
            # geçerliliği yukarıda kontrol edildi, yazma sudo ile yapılır.
            request.sudo().write({'state': 'cancel'})
            request.activity_ids.sudo().action_feedback(
                feedback=_('Talep iptal edildi.'))
        return True
