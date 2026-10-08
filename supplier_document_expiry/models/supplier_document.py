# -*- coding: utf-8 -*-
from odoo import _, api, fields, models

STATUS_SELECTION = [
    ('green', '🟢 Geçerli'),
    ('yellow', '🟡 Sarı'),
    ('orange', '🟠 Turuncu'),
    ('red', '🔴 Süresi Dolmuş'),
]

EXPIRY_ACTIVITY_TYPE = \
    'supplier_document_expiry.mail_activity_type_document_expiry'


class SupplierDocument(models.Model):
    _name = 'supplier.document'
    _description = 'Tedarikçi Belgesi'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'validity_date, id'

    partner_id = fields.Many2one(
        'res.partner', string='Tedarikçi', required=True, index=True,
        ondelete='cascade')
    name = fields.Char(string='Belge Adı', required=True)
    document_type_id = fields.Many2one(
        'supplier.document.type', string='Belge Türü', required=True,
        index=True, ondelete='restrict')
    responsible_user_id = fields.Many2one(
        'res.users', string='Sorumlu', index=True,
        default=lambda self: self.env.user,
        domain="[('share', '=', False)]")
    validity_date = fields.Date(
        string='Geçerlilik Tarihi', required=True, index=True)
    remaining_days = fields.Integer(
        string='Kalan Gün', compute='_compute_status', store=True)
    status = fields.Selection(
        STATUS_SELECTION, string='Durum', compute='_compute_status',
        store=True, tracking=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'supplier_document_attachment_rel',
        'document_id', 'attachment_id', string='Belgeler')
    last_notified_status = fields.Selection(
        STATUS_SELECTION, string='Son Bildirilen Durum',
        default='green', readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company', string='Şirket', index=True,
        default=lambda self: self.env.company)
    active = fields.Boolean(string='Aktif', default=True)

    # ------------------------------------------------------------
    # Hesaplamalar
    # ------------------------------------------------------------

    @api.depends('validity_date', 'document_type_id',
                 'document_type_id.warning_days_yellow',
                 'document_type_id.warning_days_orange')
    def _compute_status(self):
        today = fields.Date.context_today(self)
        for doc in self:
            if not doc.validity_date or not doc.document_type_id:
                doc.remaining_days = False
                doc.status = False
                continue
            days = (doc.validity_date - today).days
            doc.remaining_days = days
            if days <= 0:
                doc.status = 'red'
            elif days <= doc.document_type_id.warning_days_orange:
                doc.status = 'orange'
            elif days <= doc.document_type_id.warning_days_yellow:
                doc.status = 'yellow'
            else:
                doc.status = 'green'

    # ------------------------------------------------------------
    # Ek dosyalar
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        documents = super().create(vals_list)
        documents._sync_document_attachments()
        return documents

    def write(self, vals):
        res = super().write(vals)
        if 'attachment_ids' in vals:
            self._sync_document_attachments()
        return res

    def _sync_document_attachments(self):
        """Satır kaydedilmeden önce yüklenen eklerin res_model/res_id
        bilgisini belge kaydına bağlar; böylece standart attachment
        erişim kontrolü belge yetkileri üzerinden çalışır."""
        for doc in self:
            misplaced = doc.attachment_ids.filtered(
                lambda a: a.res_model != 'supplier.document'
                or a.res_id != doc.id)
            if misplaced:
                misplaced.sudo().write({
                    'res_model': 'supplier.document',
                    'res_id': doc.id,
                })

    # ------------------------------------------------------------
    # Cron / uyarılar
    # ------------------------------------------------------------

    @api.model
    def _cron_check_expiry(self):
        """Tüm belgelerin durumunu bugüne göre yeniden hesaplar ve
        seviye değişimlerinde sorumluya aktivite uyarısı üretir."""
        documents = self.search([('active', '=', True)])
        # status store edilmiş computed alan; tarih geçişiyle tetiklenmez
        documents._compute_status()
        documents._notify_status_changes()

    def _notify_status_changes(self):
        act_type = self.env.ref(EXPIRY_ACTIVITY_TYPE,
                                raise_if_not_found=False)
        for doc in self:
            status = doc.status or 'green'
            if status == doc.last_notified_status:
                continue
            doc.last_notified_status = status
            doc._close_expiry_activities(act_type)
            if status != 'green':
                doc._schedule_expiry_activities(act_type)

    def _notification_users(self):
        """Uyarı öncelikle belge sorumlusuna; sorumlu yoksa Tedarikçi
        Belgeleri / Yönetici grubu üyelerine gider."""
        self.ensure_one()
        if self.responsible_user_id:
            return self.responsible_user_id
        manager_group = self.env.ref(
            'supplier_document_expiry.group_supplier_document_manager',
            raise_if_not_found=False)
        return manager_group.all_user_ids if manager_group \
            else self.env['res.users']

    def _expiry_activity_summary(self):
        self.ensure_one()
        if self.status == 'yellow':
            return _('Tedarikçi belgesi sarı uyarı seviyesinde')
        if self.status == 'orange':
            return _('Tedarikçi belgesi turuncu uyarı seviyesinde')
        return _('Tedarikçi belgesinin süresi doldu')

    def _schedule_expiry_activities(self, act_type):
        self.ensure_one()
        if not act_type:
            return
        for user in self._notification_users().filtered('active'):
            self.activity_schedule(
                EXPIRY_ACTIVITY_TYPE,
                user_id=user.id,
                date_deadline=self.validity_date,
                summary=self._expiry_activity_summary(),
                note=_(
                    '%(partner)s tedarikçisine ait "%(doc)s" belgesinin '
                    'geçerlilik tarihi %(date)s.<br/>'
                    'Kalan gün: %(days)s<br/>Durum: %(status)s',
                    partner=self.partner_id.display_name,
                    doc=self.display_name,
                    date=self.validity_date,
                    days=self.remaining_days,
                    status=dict(
                        self._fields['status'].selection).get(
                            self.status)))

    def _close_expiry_activities(self, act_type=None):
        act_type = act_type or self.env.ref(
            EXPIRY_ACTIVITY_TYPE, raise_if_not_found=False)
        if not act_type:
            return
        for doc in self:
            activities = doc.activity_ids.filtered(
                lambda a: a.activity_type_id == act_type)
            if activities:
                activities.action_feedback(
                    feedback=_('Belge durumu güncellendi.'))
