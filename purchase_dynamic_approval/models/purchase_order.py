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
        copy=False, tracking=True, check_company=True,
        help="Kademeli onayda geçerli aşama; onayı beklenen barem.")
    approval_final_tier_id = fields.Many2one(
        'purchase.approval.tier', string='Hedef Barem', readonly=True,
        copy=False, tracking=True, check_company=True,
        help="Sipariş tutarının denk geldiği son barem. Kademeli "
             "onayda bu bareme kadar tüm alt baremler sırayla onaylar.")
    approval_progress = fields.Char(
        string='Onay Aşaması', compute='_compute_approval_progress')
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

    # Hesaplamalar / yardımcılar

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

    def _approval_chain(self, target=None):
        """Kademeli onay zinciri: hedef bareme (dahil) kadar olan aktif
        baremleri alt tutar sırasıyla döndürür. Sipariş, zincirdeki tüm
        baremlerin gruplarından sırayla onay geçer."""
        self.ensure_one()
        target = (target or self.approval_final_tier_id
                  or self.approval_tier_id)
        if not target:
            return self.env['purchase.approval.tier']
        return self.env['purchase.approval.tier'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('amount_min', '<=', target.amount_min),
        ]).sorted('amount_min')

    def _next_approval_tier(self):
        """Zincir içinde geçerli baremden sonraki ilk baremi döndürür;
        kalan aşama yoksa boş döner."""
        self.ensure_one()
        current = self.approval_tier_id
        if not current:
            return self._approval_chain()[:1]
        return self._approval_chain().filtered(
            lambda t: t.amount_min > current.amount_min)[:1]

    def _compute_approval_progress(self):
        for order in self:
            chain = order._approval_chain()
            current = order.approval_tier_id
            if current and chain:
                step = len(chain.filtered(
                    lambda t: t.amount_min < current.amount_min)) + 1
                order.approval_progress = '%d / %d' % (step, len(chain))
            else:
                order.approval_progress = False

    def _log_approval_history(self, action, tier=None, note=False):
        History = self.env['purchase.order.approval.history'].sudo()
        for order in self:
            order_tier = tier or order.approval_tier_id
            order_note = note
            if (action in ('approve', 'reject', 'step_approve')
                    and order_tier
                    and order_tier.delegate_user_id == self.env.user):
                order_note = (note + ' ' if note else '') + '(Vekil Onaycı)'
            History.create({
                'order_id': order.id,
                'date': fields.Datetime.now(),
                'action': action,
                'tier_id': order_tier.id,
                'approval_group_id': (
                    order_tier.approval_group_id or order.approval_group_id).id,
                'user_id': self.env.user.id,
                'amount_total': order.amount_total,
                'note': order_note or False,
            })

    def _schedule_approval_activities(self):
        self.ensure_one()
        approvers = (
            self.approval_group_id.all_user_ids
            | self.approval_tier_id.delegate_user_id).filtered('active')
        chain = self._approval_chain()
        step = len(chain.filtered(
            lambda t: t.amount_min < self.approval_tier_id.amount_min)) + 1
        step_txt = (
            _('<br/>Onay aşaması: %d/%d', step, len(chain))
            if len(chain) > 1 else '')
        for user in approvers:
            self.activity_schedule(
                APPROVAL_ACTIVITY_TYPE,
                user_id=user.id,
                summary=_('Satınalma siparişi onayı bekliyor'),
                note=_(
                    '%(po)s numaralı satınalma siparişi onayınızı '
                    'bekliyor.<br/>Toplam tutar: %(amount)s<br/>'
                    'Onay baremi: %(tier)s<br/>'
                    'Beklenen onay grubu: %(group)s%(step)s',
                    po=self.name,
                    amount=self.currency_id.format(self.amount_total),
                    tier=self.approval_tier_id.display_name,
                    group=self.approval_group_id.display_name,
                    step=step_txt))

    def _close_approval_activities(self, feedback=False):
        act_type = self.env.ref(APPROVAL_ACTIVITY_TYPE)
        for order in self:
            activities = order.activity_ids.filtered(
                lambda a: a.activity_type_id == act_type)
            if activities:
                activities.action_feedback(feedback=feedback)

    def _check_approval_permission(self):
        self.ensure_one()
        # Satır kilidi: iki onaylayıcının aynı siparişi eşzamanlı
        # onaylaması/reddetmesi çift karar yazımını engeller.
        self.env.cr.execute(
            "SELECT id FROM purchase_order WHERE id = %s FOR UPDATE",
            (self.id,))
        self.invalidate_recordset(['state', 'approval_required'])
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

    # Standart onay akışına entegrasyon

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
        # Red / iptal sonrası taslaktan yeniden onaya gönderilen siparişte
        # eski karar bilgisi kalmasın; yeni tutar bareme girmiyorsa sipariş
        # "Reddedildi" uyarısıyla onaylanmış görünürdü. Geçmiş korunur.
        self.filtered(
            lambda o: o.state in ('draft', 'sent')
            and o.approval_state != 'none'
        ).write({
            'approval_required': False,
            'approval_state': 'none',
            'approval_tier_id': False,
            'approval_final_tier_id': False,
            'submitted_amount': 0.0,
            'approver_id': False,
            'approve_date': False,
        })
        res = super().button_confirm()
        for order in self.filtered(lambda o: o.state == 'to approve'):
            order._start_approval_process()
        return res

    def _start_approval_process(self):
        self.ensure_one()
        target = self._find_approval_tier()
        if not target:
            return
        chain = self._approval_chain(target)
        first = chain[:1]
        if (self.approval_state == 'waiting'
                and self.approval_tier_id == first
                and self.approval_final_tier_id == target):
            return
        missing = chain.filtered(
            lambda t: not t.approval_group_id.all_user_ids.filtered(
                'active') and not t.delegate_user_id)
        if missing:
            raise UserError(_(
                'Bu satınalma siparişinin onay zincirindeki şu '
                'baremlerde uygun bir onaylayıcı bulunmamaktadır: %s',
                ', '.join(missing.mapped('display_name'))))
        self.write({
            'approval_required': True,
            'approval_state': 'waiting',
            'approval_tier_id': first.id,
            'approval_final_tier_id': target.id,
            'submitted_amount': self.amount_total,
            'approver_id': False,
            'approve_date': False,
        })
        self._log_approval_history('submit', tier=first)
        self._schedule_approval_activities()
        if len(chain) > 1:
            self.message_post(body=_(
                'Sipariş %(total)s aşamalı onaya gönderildi (son barem: '
                '%(final)s). İlk onay %(group)s grubunda — barem: '
                '%(tier)s, tutar: %(amount)s.',
                total=len(chain), final=target.display_name,
                group=first.approval_group_id.display_name,
                tier=first.display_name,
                amount=self.currency_id.format(self.amount_total)))
        else:
            self.message_post(body=_(
                'Sipariş %(group)s grubunun onayına gönderildi. '
                'Onay baremi: %(tier)s, tutar: %(amount)s.',
                group=first.approval_group_id.display_name,
                tier=first.display_name,
                amount=self.currency_id.format(self.amount_total)))

    # Onay / red / taslak aksiyonları

    def action_dynamic_approve(self):
        for order in self:
            order._check_approval_permission()
            next_tier = order._next_approval_tier()
            if next_tier:
                order._advance_approval_step(next_tier)
            else:
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
                order.with_context(
                    dynamic_approval_bypass=True).button_approve()
        return True

    def _advance_approval_step(self, next_tier):
        """Kademeli onayda geçerli aşamayı tamamlayıp siparişi zincirdeki
        bir sonraki baremin grubunun onayına iletir."""
        self.ensure_one()
        current = self.approval_tier_id
        chain = self._approval_chain()
        step = len(chain.filtered(
            lambda t: t.amount_min < current.amount_min)) + 1
        self._log_approval_history('step_approve', note=_(
            'Aşama %(step)s/%(total)s onaylandı.',
            step=step, total=len(chain)))
        self._close_approval_activities(feedback=_(
            'Onay aşaması tamamlandı, üst kademeye iletildi.'))
        self.approval_tier_id = next_tier.id
        self._log_approval_history('submit', tier=next_tier)
        if (next_tier.approval_group_id.all_user_ids.filtered('active')
                or next_tier.delegate_user_id):
            self._schedule_approval_activities()
        else:
            self.message_post(body=_(
                'UYARI: "%(group)s" grubunda uygun bir onaylayıcı '
                'bulunmamaktadır; onay tamamlanamaz.',
                group=next_tier.approval_group_id.display_name))
        self.message_post(body=_(
            'Onay aşaması %(step)s/%(total)s %(user)s tarafından '
            'tamamlandı (onay grubu: %(group)s); sipariş %(next)s '
            'grubunun onayına iletildi.',
            step=step, total=len(chain), user=self.env.user.name,
            group=current.approval_group_id.display_name,
            next=next_tier.approval_group_id.display_name))

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
            # Doğrudan state yazımı yerine standart akış: button_draft
            # RFQ'nun yeniden başlatılması gibi standart yan etkileri
            # de çalıştırır.
            order.button_draft()
            order.write({
                'approval_required': False,
                'approval_state': 'none',
                'approval_tier_id': False,
                'approval_final_tier_id': False,
                'submitted_amount': 0.0,
                'approver_id': False,
                'approve_date': False,
            })
        return True

    # Tutar değişikliği kontrolü

    def write(self, vals):
        res = super().write(vals)
        if 'currency_id' in vals or 'company_id' in vals:
            self._check_approval_amount_change()
        return res

    def _check_approval_amount_change(self):
        """Onay bekleyen siparişte tutar değiştiyse hedef baremi yeniden
        değerlendirir: hedef aynıysa yalnızca tutarı günceller, hedef
        kalmadıysa ya da tamamlanan aşamalar yeni hedefi zaten
        kapsıyorsa otomatik onaylar, hedef değiştiyse zinciri güncelleyip
        geçerli aşamadan devam ettirir."""
        for order in self.filtered(
                lambda o: o.state == 'to approve' and o.approval_required):
            if order.currency_id.compare_amounts(
                    order.amount_total, order.submitted_amount) == 0:
                continue
            old_amount = order.submitted_amount
            old_target = (order.approval_final_tier_id
                          or order.approval_tier_id)
            new_target = order._find_approval_tier()
            old_fmt = order.currency_id.format(old_amount)
            new_fmt = order.currency_id.format(order.amount_total)

            if new_target == old_target:
                order.submitted_amount = order.amount_total
                order._log_approval_history('amount_change', note=_(
                    'Tutar %(old)s → %(new)s olarak değişti; onay baremi '
                    'aynı kaldı.', old=old_fmt, new=new_fmt))
                order.message_post(body=_(
                    'Sipariş toplamı %(old)s → %(new)s olarak değişti; '
                    'onay baremi aynı kaldı (%(tier)s).',
                    old=old_fmt, new=new_fmt, tier=old_target.display_name))
            elif not new_target:
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
                current_min = (order.approval_tier_id.amount_min
                               if order.approval_tier_id else -1)
                remaining = order._approval_chain(new_target).filtered(
                    lambda t: t.amount_min > current_min)
                order._log_approval_history('tier_change', note=_(
                    'Tutar %(old)s → %(new)s olarak değişti; hedef barem '
                    '%(oldt)s → %(newt)s olarak güncellendi.',
                    old=old_fmt, new=new_fmt,
                    oldt=old_target.display_name,
                    newt=new_target.display_name))
                order.write({
                    'approval_final_tier_id': new_target.id,
                    'submitted_amount': order.amount_total,
                })
                if not remaining:
                    # Tutar düştü; tamamlanan aşamalar yeni hedef baremi
                    # zaten kapsıyor, kalan onay kalmadı.
                    order._close_approval_activities(feedback=_(
                        'Tutar değişikliği sonrası kalan onay aşaması '
                        'kalmadı.'))
                    order.write({
                        'approval_state': 'approved',
                        'approver_id': self.env.user.id,
                        'approve_date': fields.Datetime.now(),
                    })
                    order._log_approval_history('auto_approve', note=_(
                        'Tutar %(old)s → %(new)s olarak değişti; yeni '
                        'hedef barem tamamlanan aşamaların altında '
                        'kaldığı için sipariş otomatik onaylandı.',
                        old=old_fmt, new=new_fmt))
                    order.message_post(body=_(
                        'Sipariş toplamı %(old)s → %(new)s olarak '
                        'değişti; kalan onay aşaması kalmadı, sipariş '
                        'otomatik onaylandı.', old=old_fmt, new=new_fmt))
                    order.with_context(
                        dynamic_approval_bypass=True).button_approve()
                else:
                    missing = remaining.filtered(
                        lambda t:
                        not t.approval_group_id.all_user_ids.filtered(
                            'active') and not t.delegate_user_id)
                    if missing:
                        order.message_post(body=_(
                            'UYARI: şu onay baremlerinde uygun bir '
                            'onaylayıcı bulunmamaktadır: %(tiers)s',
                            tiers=', '.join(
                                missing.mapped('display_name'))))
                    order.message_post(body=_(
                        'Sipariş toplamı %(old)s → %(new)s olarak '
                        'değişti; hedef barem %(tier)s olarak '
                        'güncellendi. Onay, %(group)s grubundaki '
                        'aşamadan devam ediyor.',
                        old=old_fmt, new=new_fmt,
                        tier=new_target.display_name,
                        group=order.approval_group_id.display_name))
