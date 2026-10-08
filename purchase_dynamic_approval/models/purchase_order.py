# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

APPROVAL_ACTIVITY_TYPE = \
    'purchase_dynamic_approval.mail_activity_type_purchase_order_approval'


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    approval_required = fields.Boolean(
        string='Onay Gerekiyor', readonly=True, copy=False, tracking=True)
    approval_state = fields.Selection([
        ('none', 'Onay Yok'),
        ('waiting', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
    ], string='Onay Durumu', default='none', readonly=True, copy=False,
        tracking=True)
    approval_tier_id = fields.Many2one(
        'purchase.approval.tier', string='Onay Baremı', readonly=True,
        copy=False, tracking=True, check_company=True)
    approval_group_id = fields.Many2one(
        'res.groups', string='Beklenen Onay Grubu',
        related='approval_tier_id.approval_group_id', store=True,
        readonly=True)
    approval_delegate_id = fields.Many2one(
        'res.users', string='Vekil Onaycı',
        related='approval_tier_id.delegate_user_id', store=True,
        readonly=True)
    submitted_amount = fields.Monetary(
        string='Onaya Gönderilen Tutar', readonly=True, copy=False,
        currency_field='currency_id')
    approver_id = fields.Many2one(
        'res.users', string='Onaylayan', readonly=True, copy=False,
        tracking=True)
    approve_date = fields.Datetime(
        string='Onay / Red Tarihi', readonly=True, copy=False)
    can_approve = fields.Boolean(
        string='Onay Yetkisi Var', compute='_compute_can_approve')
    approval_history_ids = fields.One2many(
        'purchase.order.approval.history', 'order_id',
        string='Onay Geçmişi', readonly=True, copy=False)

    # ------------------------------------------------------------
    # Hesaplamalar / yardımcılar
    # ------------------------------------------------------------

    def _compute_can_approve(self):
        user = self.env.user
        for order in self:
            tier = order.approval_tier_id
            order.can_approve = bool(
                order.state == 'to approve'
                and order.approval_required
                and (order.approval_group_id
                     and order.approval_group_id in user.all_group_ids
                     or tier and tier.delegate_user_id == user))

    def _find_approval_tier(self):
        """Sipariş toplamının (şirket para birimine çevrilmiş) dahil
        olduğu aktif onay baremini döndürür."""
        self.ensure_one()
        amount = self.currency_id._convert(
            self.amount_total, self.company_id.currency_id,
            self.company_id, self.date_order or fields.Date.today())
        return self.env['purchase.approval.tier'].sudo()._find_for_amount(
            self.company_id, amount)

    def _log_approval_history(self, action, tier=None, note=False):
        History = self.env['purchase.order.approval.history'].sudo()
        for order in self:
            tier = tier or order.approval_tier_id
            if (action in ('approve', 'reject') and tier
                    and tier.delegate_user_id == self.env.user):
                note = (note + ' ' if note else '') + '(Vekil Onaycı)'
            History.create({
                'order_id': order.id,
                'date': fields.Datetime.now(),
                'action': action,
                'tier_id': tier.id,
                'approval_group_id': (
                    tier.approval_group_id or order.approval_group_id).id,
                'user_id': self.env.user.id,
                'amount_total': order.amount_total,
                'note': note or False,
            })

    def _schedule_approval_activities(self):
        self.ensure_one()
        approvers = (
            self.approval_group_id.all_user_ids
            | self.approval_tier_id.delegate_user_id).filtered('active')
        for user in approvers:
            self.activity_schedule(
                APPROVAL_ACTIVITY_TYPE,
                user_id=user.id,
                summary=_('Satınalma siparişi onayı bekliyor'),
                note=_(
                    '%(po)s numaralı satınalma siparişi onayınızı '
                    'bekliyor.<br/>Toplam tutar: %(amount)s<br/>'
                    'Onay baremi: %(tier)s<br/>'
                    'Beklenen onay grubu: %(group)s',
                    po=self.name,
                    amount=self.currency_id.format(self.amount_total),
                    tier=self.approval_tier_id.display_name,
                    group=self.approval_group_id.display_name))

    def _close_approval_activities(self, feedback=False):
        act_type = self.env.ref(APPROVAL_ACTIVITY_TYPE)
        for order in self:
            activities = order.activity_ids.filtered(
                lambda a: a.activity_type_id == act_type)
            if activities:
                activities.action_feedback(feedback=feedback)

    def _check_approval_permission(self):
        self.ensure_one()
        if self.state != 'to approve' or not self.approval_required:
            raise UserError(_('Bu sipariş onay beklemiyor.'))
        group = self.approval_group_id
        delegate = self.approval_tier_id.delegate_user_id
        if not delegate and (
                not group or not group.all_user_ids.filtered('active')):
            raise UserError(_(
                'Bu satınalma siparişi için tanımlanan onay grubunda '
                'uygun bir onaylayıcı bulunmamaktadır.'))
        if (self.env.user != delegate
                and (not group
                     or group not in self.env.user.all_group_ids)):
            raise UserError(_(
                'Bu sipariş üzerinde yalnızca "%s" grubuna üye '
                'kullanıcılar veya baremde tanımlı vekil onaycı '
                'onay/red işlemi yapabilir.',
                group.display_name if group else ''))

    # ------------------------------------------------------------
    # Standart onay akışına entegrasyon
    # ------------------------------------------------------------

    def _approval_allowed(self):
        """Tutara denk gelen bir onay baremi varsa standart onay
        mekanizmasından bağımsız olarak onay gerekir. Dinamik onay
        aksiyonları `dynamic_approval_bypass` bağlamıyla çalışır."""
        if self.env.context.get('dynamic_approval_bypass'):
            return True
        self.ensure_one()
        if self._find_approval_tier():
            return False
        return super()._approval_allowed()

    def button_confirm(self):
        res = super().button_confirm()
        for order in self.filtered(lambda o: o.state == 'to approve'):
            order._start_approval_process()
        return res

    def _start_approval_process(self):
        self.ensure_one()
        tier = self._find_approval_tier()
        if not tier:
            return
        if self.approval_state == 'waiting' \
                and self.approval_tier_id == tier:
            return
        if (not tier.approval_group_id.all_user_ids.filtered('active')
                and not tier.delegate_user_id):
            raise UserError(_(
                'Bu satınalma siparişi için tanımlanan onay grubunda '
                'uygun bir onaylayıcı bulunmamaktadır.'))
        self.write({
            'approval_required': True,
            'approval_state': 'waiting',
            'approval_tier_id': tier.id,
            'submitted_amount': self.amount_total,
            'approver_id': False,
            'approve_date': False,
        })
        self._log_approval_history('submit', tier=tier)
        self._schedule_approval_activities()
        self.message_post(body=_(
            'Sipariş %(group)s grubunun onayına gönderildi. '
            'Onay baremi: %(tier)s, tutar: %(amount)s.',
            group=tier.approval_group_id.display_name,
            tier=tier.display_name,
            amount=self.currency_id.format(self.amount_total)))

    # ------------------------------------------------------------
    # Onay / red / taslak aksiyonları
    # ------------------------------------------------------------

    def action_dynamic_approve(self):
        for order in self:
            order._check_approval_permission()
            order._log_approval_history('approve')
            order.write({
                'approval_state': 'approved',
                'approver_id': self.env.user.id,
                'approve_date': fields.Datetime.now(),
            })
            order._close_approval_activities(
                feedback=_('Sipariş onaylandı.'))
            order.message_post(body=_(
                'Satınalma siparişi %(user)s tarafından onaylandı. '
                'Onay grubu: %(group)s.',
                user=self.env.user.name,
                group=order.approval_group_id.display_name))
            order.with_context(dynamic_approval_bypass=True).button_approve()
        return True

    def action_dynamic_reject(self):
        self.ensure_one()
        self._check_approval_permission()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Red Nedeni'),
            'res_model': 'purchase.order.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def _do_reject(self, reason):
        self.ensure_one()
        self._check_approval_permission()
        self._log_approval_history('reject', note=reason)
        self.write({
            'approval_state': 'rejected',
            'approver_id': self.env.user.id,
            'approve_date': fields.Datetime.now(),
        })
        self._close_approval_activities(
            feedback=_('Sipariş reddedildi.'))
        self.message_post(body=_(
            'Satınalma siparişi %(user)s tarafından reddedildi. '
            'Red nedeni: %(reason)s',
            user=self.env.user.name, reason=reason))
        self.button_draft()

    def button_cancel(self):
        for order in self.filtered(
                lambda o: o.state == 'to approve' and o.approval_required):
            order._close_approval_activities(
                feedback=_('Sipariş iptal edildi.'))
            order._log_approval_history(
                'cancel', note=_('Sipariş iptal edildi.'))
        return super().button_cancel()

    def action_reset_to_draft(self):
        for order in self.filtered(
                lambda o: o.state == 'to approve' and o.approval_required):
            order._close_approval_activities(
                feedback=_('Onay süreci sonlandırıldı.'))
            order._log_approval_history(
                'reset', note=_('Onay süreci sonlandırıldı, sipariş '
                                'taslağa alındı.'))
            order.message_post(body=_(
                'Onay süreci sonlandırıldı, sipariş taslağa alındı.'))
            order.write({
                'state': 'draft',
                'approval_required': False,
                'approval_state': 'none',
                'approval_tier_id': False,
                'submitted_amount': 0.0,
                'approver_id': False,
                'approve_date': False,
            })
        return True

    # ------------------------------------------------------------
    # Tutar değişikliği kontrolü
    # ------------------------------------------------------------

    def write(self, vals):
        res = super().write(vals)
        if 'currency_id' in vals or 'company_id' in vals:
            self._check_approval_amount_change()
        return res

    def _check_approval_amount_change(self):
        """Onay bekleyen siparişte tutar değiştiyse baremi yeniden
        değerlendirir; barem değiştiyse onay sürecini yeni grupla
        yeniden başlatır, barem kalmadıysa otomatik onaylar."""
        for order in self.filtered(
                lambda o: o.state == 'to approve' and o.approval_required):
            if order.currency_id.compare_amounts(
                    order.amount_total, order.submitted_amount) == 0:
                continue
            old_amount = order.submitted_amount
            old_tier = order.approval_tier_id
            new_tier = order._find_approval_tier()
            old_fmt = order.currency_id.format(old_amount)
            new_fmt = order.currency_id.format(order.amount_total)

            if new_tier == old_tier:
                order.submitted_amount = order.amount_total
                order._log_approval_history('amount_change', note=_(
                    'Tutar %(old)s → %(new)s olarak değişti; onay baremi '
                    'aynı kaldı.', old=old_fmt, new=new_fmt))
                order.message_post(body=_(
                    'Sipariş toplamı %(old)s → %(new)s olarak değişti; '
                    'onay baremi aynı kaldı (%(tier)s).',
                    old=old_fmt, new=new_fmt, tier=old_tier.display_name))
            elif not new_tier:
                order._close_approval_activities(feedback=_(
                    'Tutar değişikliği sonrası onay gerekmedi.'))
                order.write({
                    'submitted_amount': order.amount_total,
                    'approval_required': False,
                    'approval_state': 'approved',
                })
                order._log_approval_history('auto_approve', note=_(
                    'Tutar %(old)s → %(new)s olarak değişti; yeni tutara '
                    'denk gelen onay baremi bulunamadı, sipariş otomatik '
                    'onaylandı.', old=old_fmt, new=new_fmt))
                order.message_post(body=_(
                    'Sipariş toplamı %(old)s → %(new)s olarak değişti; '
                    'yeni tutar onay gerektirmiyor, sipariş otomatik '
                    'onaylandı.', old=old_fmt, new=new_fmt))
                order.with_context(
                    dynamic_approval_bypass=True).button_approve()
            else:
                order._close_approval_activities(feedback=_(
                    'Onay baremi değişti, onay süreci yeniden başlatıldı.'))
                order._log_approval_history('tier_change', note=_(
                    'Tutar %(old)s → %(new)s olarak değişti; barem '
                    '%(oldt)s → %(newt)s olarak güncellendi.',
                    old=old_fmt, new=new_fmt,
                    oldt=old_tier.display_name, newt=new_tier.display_name))
                order.write({
                    'approval_tier_id': new_tier.id,
                    'submitted_amount': order.amount_total,
                    'approval_state': 'waiting',
                    'approver_id': False,
                    'approve_date': False,
                })
                order._log_approval_history('submit', tier=new_tier)
                if (new_tier.approval_group_id.all_user_ids.filtered('active')
                        or new_tier.delegate_user_id):
                    order._schedule_approval_activities()
                else:
                    order.message_post(body=_(
                        'UYARI: "%(group)s" grubunda uygun bir onaylayıcı '
                        'bulunmamaktadır; onay tamamlanamaz.',
                        group=new_tier.approval_group_id.display_name))
                order.message_post(body=_(
                    'Sipariş toplamı %(old)s → %(new)s olarak değişti; '
                    'onay süreci %(group)s grubu için yeniden başlatıldı.',
                    old=old_fmt, new=new_fmt,
                    group=new_tier.approval_group_id.display_name))
