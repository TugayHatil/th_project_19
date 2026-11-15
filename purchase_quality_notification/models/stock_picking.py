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

    def _pqn_assert_quality_checked(self):
        # A quality-controlled product must not be received into stock
        # while it has a pending check — and never without a check at
        # all. Quantities are left untouched: the warehouse user
        # blanks a line he wants to defer to the backorder himself.
        lines = self.move_line_ids.filtered(
            lambda l: l.quantity > 0
            and l._is_quality_controlled_receipt_line())
        # A check that lost its line when the quantity was zeroed is
        # re-attached to the new line — it counts as sent.
        Check = self.env['quality.check']
        for line in lines.filtered(lambda l: l.check_state == 'no_checks'):
            detached = Check.search([
                ('picking_id', '=', line.picking_id.id),
                ('product_id', '=', line.product_id.id),
                ('measure_on', '=', 'move_line'),
                ('move_line_id', '=', False),
                ('quality_state', '=', 'none')], limit=1)
            if detached:
                detached.move_line_id = line.id
        missing = lines.filtered(
            lambda l: l.check_state == 'no_checks')
        if missing:
            raise UserError(_(
                'Kalite Kontrolü Eksik\n\n'
                'Aşağıdaki ürünler için hiç kalite kontrolü bulunmadığından '
                'depoya kabul işlemi yapılamaz:\n\n'
                '%s\n\n'
                'İlgili satırda "KK\'ya Gönder" seçeneğini işaretleyip '
                '"Kaliteye Gönder" butonuyla kontrol başlatın, '
                'ya da satır miktarını sıfırlayın.',
                '\n'.join('• %s' % n for n in dict.fromkeys(
                    missing.mapped('product_id.display_name')))))
        pending = lines.filtered(
            lambda l: l.check_ids.filtered(
                lambda c: c.quality_state == 'none'))
        if pending:
            raise UserError(_(
                'Kalite Onayı Eksik\n\n'
                'Aşağıdaki ürünlerin kalite kontrolü henüz '
                'tamamlanmadığı için depoya kabul işlemi yapılamaz:\n\n'
                '%s\n\n'
                'Kalite ekibi kontrolleri tamamladığında satırları '
                'doğrulayabilirsiniz. Bekletmek istediğiniz ürünlerin '
                'satır miktarını sıfırlayıp tekrar deneyin; '
                'gönderilmemiş kontroller için ilgili satırda '
                '"KK\'ya Gönder" seçeneğini işaretleyin ve '
                '"Kaliteye Gönder" butonuna tıklayın.',
                '\n'.join('• %s' % n for n in dict.fromkeys(
                    pending.mapped('product_id.display_name')))))

    def _pre_action_done_hook(self):
        self._pqn_assert_quality_checked()
        res = super()._pre_action_done_hook()
        # A pending check whose whole line is left unreceived (quantity 0)
        # must ride to the backorder untouched — it was already sent to
        # quality, so the validation wizard should not pop for it.
        if isinstance(res, dict) and res.get('res_model') == 'quality.check.wizard':
            ctx = res.get('context') or {}
            ids = ctx.get('default_check_ids') or []
            pending_lines = self.env['quality.check'].browse(ids).filtered(
                lambda c: (c.measure_on == 'move_line'
                           and (not c.move_line_id
                                or not c.move_line_id.quantity))
                           or c._pqn_needs_send())
            keep = [i for i in ids if i not in pending_lines.ids]
            if not keep:
                return True
            if len(keep) != len(ids):
                ctx = dict(ctx, default_check_ids=keep,
                           default_current_check_id=keep[0])
                res = dict(res, context=ctx)
        return res

    def _action_done(self):
        self._pqn_assert_quality_checked()
        # Snapshot pending checks before validation: the backorder split
        # can unlink the move lines they point at, and the checks are
        # cascade-deleted with them. They are restored on the new lines.
        Check = self.env['quality.check']
        pending = Check.search([
            ('picking_id', 'in', self.ids),
            ('quality_state', '=', 'none')])
        snapshot = pending.read([
            'product_id', 'test_type_id', 'team_id', 'company_id',
            'failure_location_id', 'measure_on', 'pqn_sent', 'point_id'])
        res = super()._action_done()
        self._pqn_sync_backorder_checks(pending, snapshot)
        return res

    def _pqn_sync_backorder_checks(self, pending, snapshot):
        # When a partial validation creates a backorder, the pending
        # quality check must follow its move line to the new picking —
        # the warehouse user already sent it to quality, no re-marking.
        Check = self.env['quality.check']
        alive = pending.exists()

        def m2o(value):
            return value[0] if isinstance(value, (list, tuple)) else value

        for backorder in self.backorder_ids:
            stray = alive.filtered(
                lambda c: c.move_line_id
                and c.move_line_id.picking_id == backorder
                and c.picking_id != backorder)
            if stray:
                stray.picking_id = backorder.id
            open_lines = backorder.move_line_ids.filtered(
                lambda l: l.state not in ('done', 'cancel'))
            # Checks deleted with their split lines are recreated on the
            # backorder's line for the same product — unless standard
            # Odoo already re-created one from the quality point; then
            # only the sent state is carried over.
            for row in snapshot:
                if row['id'] in alive.ids:
                    continue
                product_id = m2o(row['product_id'])
                existing = Check.search([
                    ('picking_id', '=', backorder.id),
                    ('product_id', '=', product_id),
                    ('quality_state', '=', 'none')], limit=1)
                if existing:
                    existing.pqn_sent = (
                        existing.pqn_sent or row['pqn_sent'])
                    continue
                line = open_lines.filtered(
                    lambda l: l.product_id.id == product_id)[:1]
                if line:
                    Check.create({
                        'picking_id': backorder.id,
                        'move_line_id': line.id,
                        'measure_on': 'move_line',
                        'product_id': product_id,
                        'point_id': m2o(row['point_id']),
                        'test_type_id': m2o(row['test_type_id']),
                        'team_id': m2o(row['team_id']),
                        'company_id': m2o(row['company_id']),
                        'failure_location_id': m2o(row['failure_location_id']),
                        'pqn_sent': row['pqn_sent'],
                    })
            # Pending checks whose line was unlinked but survived get
            # re-attached to the backorder's line for the same product —
            # unless the backorder already holds a pending check for
            # that product (re-created from the point), which then
            # absorbs the sent state and the stray check is dropped.
            for check in alive.exists().filtered(
                    lambda c: c.picking_id in self and not c.move_line_id):
                existing = Check.search([
                    ('picking_id', '=', backorder.id),
                    ('product_id', '=', check.product_id.id),
                    ('quality_state', '=', 'none')], limit=1)
                if existing:
                    existing.pqn_sent = (
                        existing.pqn_sent or check.pqn_sent)
                    check.unlink()
                    continue
                line = open_lines.filtered(
                    lambda l: l.product_id == check.product_id)[:1]
                if line:
                    check.write({
                        'picking_id': backorder.id,
                        'move_line_id': line.id})
                elif backorder.move_ids.filtered(
                        lambda m: m.product_id == check.product_id):
                    check.picking_id = backorder.id
            # A flag the user set but had not sent yet also carries to the
            # remainder move created by the split.
            for move in backorder.move_ids:
                if not move.quality_send_ok and self.move_ids.filtered(
                        lambda m: m.product_id == move.product_id
                        and m.quality_send_ok):
                    move.quality_send_ok = True

    def check_quality(self):
        res = super().check_quality()
        # The standard button only opens checks measured per operation /
        # product; our gated lines use measure_on='move_line' checks that
        # are otherwise reachable only via the per-line icon. Include them
        # in the wizard so the header button stays a single entry point.
        pending = self.check_ids.filtered(
            lambda c: c.quality_state == 'none'
            and c.measure_on == 'move_line'
            and c.pqn_sent
            and (not c.move_line_id
                 or c.move_line_id._is_quality_controlled_receipt_line()))
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
        # Create quality checks only for the lines the warehouse user
        # flagged with the per-row "Kaliteye Gönder" checkbox.
        marked = self.move_ids.filtered(
            lambda m: m.quality_send_ok and m.quality_purchase_ok
            and m.state not in ('done', 'cancel'))
        checks = marked._pqn_send_quality_checks()
        # The flag stays set — it marks which rows were sent to quality.
        if checks:
            self.message_post(body=_(
                '%(count)s satır kaliteye gönderildi: %(checks)s',
                count=len(checks),
                checks=', '.join(checks.mapped('display_name'))))
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
