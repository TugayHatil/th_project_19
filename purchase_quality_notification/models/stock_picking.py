# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    show_quality_notify = fields.Boolean(
        compute='_compute_show_quality_notify')
    quality_notified = fields.Boolean(
        string='Kaliteye Bildirildi', default=False, copy=False, readonly=True)
    quality_picking_url = fields.Char(compute='_compute_quality_picking_url')

    @api.depends('picking_type_code', 'state', 'move_ids.product_id',
                 'move_ids.product_id.product_tmpl_id.quality_purchase_ok')
    def _compute_show_quality_notify(self):
        for picking in self:
            picking.show_quality_notify = (
                picking.picking_type_code == 'incoming'
                and picking.state not in ('draft', 'cancel')
                and any(picking.move_ids.mapped(
                    lambda m: m.product_id.product_tmpl_id.quality_purchase_ok))
            )

    def _compute_quality_picking_url(self):
        base_url = self.get_base_url()
        for picking in self:
            picking.quality_picking_url = (
                f'{base_url}/mail/view?model=stock.picking&res_id={picking.id}'
                if picking.id else False)

    def _get_quality_notification_partners(self):
        group = self.env.ref('quality.group_quality_user',
                             raise_if_not_found=False)
        users = (group.all_user_ids if group else self.env['res.users'])
        company = self.company_id
        users = users.filtered(
            lambda u: u.active and not u.share
            and (not u.company_ids or company in u.company_ids))
        partners = self.env['res.partner']
        seen_emails = set()
        for partner in users.mapped('partner_id'):
            email = partner.email and partner.email.strip()
            if email and email.lower() not in seen_emails:
                seen_emails.add(email.lower())
                partners |= partner
        return partners

    def action_send_quality_notification(self):
        self.ensure_one()
        if not self.show_quality_notify:
            raise UserError(_(
                'Bu transfer için kalite bildirimi gönderilemez.'))
        template = self.env.ref(
            'purchase_quality_notification.mail_template_purchase_quality_notify',
            raise_if_not_found=False)
        if not template:
            raise UserError(_('Kalite bildirimi e-posta şablonu bulunamadı.'))
        partners = self._get_quality_notification_partners()
        if not partners:
            raise UserError(_(
                'Main Quality Team için e-posta adresi tanımlı üye bulunamadı. '
                'Kalite (Quality / User) grubundaki kullanıcıların e-posta '
                'adreslerini kontrol edin.'))
        mail_id = template.send_mail(
            self.id, force_send=True, raise_exception=False,
            email_values={'recipient_ids': [(6, 0, partners.ids)]})
        mail = self.env['mail.mail'].sudo().browse(mail_id)
        if mail.state == 'exception':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Kalite bildirimi gönderilemedi'),
                    'message': mail.failure_reason or _(
                        'E-posta gönderimi başarısız oldu. Giden posta '
                        'sunucusu ayarlarını kontrol edin.'),
                    'type': 'warning',
                    'sticky': True,
                },
            }
        self.quality_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Kalite bildirimi'),
                'message': _('Kalite ekibine bildirim gönderildi.'),
                'type': 'success',
                'sticky': False,
            },
        }
