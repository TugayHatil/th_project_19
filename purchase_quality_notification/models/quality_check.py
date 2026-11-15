# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    pqn_sent = fields.Boolean(
        string='Kaliteye Gönderildi', default=False, copy=False,
        index=True, readonly=True,
        help='Depo "Kaliteye Gönder" ile kalite ekibine iletti. '
             'Yalnızca gönderilen kontroller işlem görebilir.')
    pqn_sent_qty = fields.Float(
        string='Kaliteye Gönderilen Miktar', readonly=True, copy=False,
        help='Depo "Kaliteye Gönder" dediği andaki satır miktarı. '
             'Ön teslimatta satır talep miktarına dönse bile '
             'kontrolün kapsamı bu miktar olarak korunur.')
    pqn_remainder = fields.Boolean(
        string='Kalan Miktar Kontrolü', readonly=True, copy=False,
        help='Gönderilen miktarın talepten eksik kalan kısmını temsil '
             'eden, henüz kaliteye gönderilmemiş bekleyen kontrol.')
    pqn_receipt_label = fields.Char(
        string='Tedarik', compute='_compute_pqn_receipt_label',
        store=True, index=True,
        help='Satınalma siparişi / transfer / tedarikçi etiketi — '
             'depo bekleyen kontrolleri tek satırda gruplar.')
    # The line qty on a backorder reverts to demand; a check already
    # sent to quality keeps covering the quantity it was sent with.
    qty_line = fields.Float(compute='_compute_qty_line')

    @api.depends('production_id.qty_producing', 'move_line_id.quantity',
                 'pqn_sent', 'pqn_sent_qty')
    def _compute_qty_line(self):
        for check in self:
            if check.production_id:
                check.qty_line = check.production_id.qty_producing
            elif check.move_line_id:
                # A sent check always shows the quantity it was sent
                # with — the line may revert to demand on a backorder
                # or be re-served in parts; neither changes what was
                # sent to quality.
                qty = check.move_line_id.quantity
                if check.pqn_sent and check.pqn_sent_qty:
                    qty = check.pqn_sent_qty
                check.qty_line = qty
            else:
                # A detached check keeps the quantity it stands for —
                # e.g. the unsent remainder of a partial receipt.
                check.qty_line = check.pqn_sent_qty or 0.0

    @api.depends('picking_id', 'picking_id.name',
                 'picking_id.purchase_id.name', 'picking_id.origin',
                 'picking_id.partner_id.name')
    def _compute_pqn_receipt_label(self):
        for check in self:
            picking = check.picking_id
            parts = [
                (picking.purchase_id or self.env['purchase.order']).name
                or picking.origin or '',
                picking.name or '',
                picking.partner_id.commercial_partner_id.name or '',
            ]
            check.pqn_receipt_label = (
                ' / '.join(p for p in parts if p) or _('(Transfersiz)'))

    @api.model_create_multi
    def create(self, vals_list):
        checks = super().create(vals_list)
        # Quantity edits before sending spawn extra move lines and
        # Odoo makes a check per line — until anything is actually
        # sent to quality a single unsent check per (product, lot)
        # is enough. The fresh check is kept and repointed to the
        # biggest line; older unsent duplicates are dropped. The
        # sent/remainder split still happens only at send time.
        for check in checks:
            if (check.quality_state != 'none' or check.pqn_sent
                    or check.pqn_remainder or not check.picking_id
                    or check.picking_id.picking_type_code != 'incoming'
                    or not check.product_id.product_tmpl_id
                            .quality_purchase_ok):
                continue
            lot_key = check.move_line_id.lot_id.id or 0
            # When a remainder already represents the not-sent part,
            # an extra line's fresh check adds nothing — drop it so
            # the split stays "sent qty + remainder" until resend.
            rem = self.search([
                ('picking_id', '=', check.picking_id.id),
                ('product_id', '=', check.product_id.id),
                ('quality_state', '=', 'none'),
                ('pqn_remainder', '=', True),
                ('id', '!=', check.id),
            ]).filtered(
                lambda c: (c.move_line_id.lot_id.id or 0) == lot_key)
            if rem:
                check.unlink()
                continue
            dup = self.search([
                ('picking_id', '=', check.picking_id.id),
                ('product_id', '=', check.product_id.id),
                ('quality_state', '=', 'none'),
                ('pqn_sent', '=', False),
                ('pqn_remainder', '=', False),
                ('id', '!=', check.id),
            ]).filtered(
                lambda c: (c.move_line_id.lot_id.id or 0) == lot_key)
            if dup:
                big = (dup | check).filtered('move_line_id').sorted(
                    key=lambda c: c.move_line_id.quantity,
                    reverse=True)[:1]
                if big and big.move_line_id != check.move_line_id:
                    check.move_line_id = big.move_line_id
                dup.unlink()
        return checks

    def _pqn_needs_send(self):
        self.ensure_one()
        return (self.quality_state == 'none'
                and not self.pqn_sent
                and self.picking_id
                and self.picking_id.picking_type_code == 'incoming'
                and self.product_id.product_tmpl_id.quality_purchase_ok)

    def _pqn_assert_sent(self):
        # Only checks the warehouse user sent to quality may be worked
        # on; internal flows (failure split, wizard confirm) carry the
        # pqn_internal flag and bypass the guard.
        if self.env.context.get('pqn_internal'):
            return
        blocked = self.filtered(lambda c: c._pqn_needs_send())
        if blocked:
            raise UserError(_(
                'Bu kontrol henüz depo tarafından kaliteye '
                'gönderilmedi: %s',
                ', '.join(blocked.mapped('display_name'))))

    def do_pass(self):
        self._pqn_assert_sent()
        return super().do_pass()

    def do_fail(self):
        if (self.env.context.get('pqn_internal')
                or self.env.context.get('from_failure_form')):
            return super().do_fail()
        self._pqn_assert_sent()
        # Failing a pending receipt check from the check form opens the
        # failure dialog (failed qty + failure location) instead of
        # failing the whole quantity — confirm_fail applies the split.
        line_checks = self.filtered(
            lambda c: c.quality_state == 'none'
            and c.picking_id
            and c.picking_id.picking_type_code == 'incoming'
            and c.measure_on == 'move_line')
        if not line_checks:
            return super().do_fail()
        first = line_checks[0]
        qty = first.qty_to_test or first.move_line_id.quantity or 1
        # The wizard record must exist before the dialog opens: the
        # failure form's fields are chained related values
        # (measure_on, potential_failure_location_ids, ...) that do
        # not resolve on an unsaved record.
        wizard = self.env['quality.check.wizard'].create({
            'check_ids': [(6, 0, line_checks.ids)],
            'current_check_id': first.id,
            'qty_tested': qty,
            'qty_failed': qty,
            'failure_location_id': (
                first.point_id.failure_location_ids
                or first.failure_location_id)[:1].id,
        })
        return {
            'name': _('Quality Check Failed'),
            'type': 'ir.actions.act_window',
            'res_model': 'quality.check.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(self.env.ref(
                'quality_control.quality_check_wizard_form_failure').id,
                'form')],
            'target': 'new',
            'context': dict(
                self.env.context,
                from_failure_form=True,
                hide_back_button=True),
        }
