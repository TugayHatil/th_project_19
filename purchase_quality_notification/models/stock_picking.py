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

    def check_quality(self):
        res = super().check_quality()
        # The standard button only opens checks measured per operation /
        # product; our gated lines use measure_on='move_line' checks that
        # are otherwise reachable only via the per-line icon. Include them
        # in the wizard so the header button stays a single entry point.
        pending = self.check_ids.filtered(
            lambda c: c.quality_state == 'none'
            and c.measure_on == 'move_line'
            and c.move_line_id._is_quality_controlled_receipt_line())
        if not pending:
            return res
        if isinstance(res, dict) and res.get('res_model') == 'quality.check.wizard':
            ctx = dict(res.get('context') or {})
            ids = list(ctx.get('default_check_ids') or [])
            ctx['default_check_ids'] = ids + [
                i for i in pending.ids if i not in ids]
            res['context'] = ctx
            return res
        action = self.env['ir.actions.actions']._for_xml_id(
            'quality_control.action_quality_check_wizard')
        action['context'] = {
            'default_check_ids': pending.ids,
            'default_current_check_id': pending[0].id,
            'default_qty_tested': pending[0].qty_to_test,
        }
        return action

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
        template.send_mail(
            self.id, force_send=True, raise_exception=False,
            email_values={'recipient_ids': [(6, 0, partners.ids)]})
        self.quality_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Kalite bildirimi'),
                'message': _('Kalite ekibine bildirim gönderildi.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
