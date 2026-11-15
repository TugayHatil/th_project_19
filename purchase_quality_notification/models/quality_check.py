# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    pqn_sent = fields.Boolean(
        string='Kaliteye Gönderildi', default=False, copy=False,
        index=True, readonly=True,
        help='Depo "Kaliteye Gönder" ile kalite ekibine iletti. '
             'Yalnızca gönderilen kontroller işlem görebilir.')

    def _pqn_needs_send(self):
        self.ensure_one()
        return (self.quality_state == 'none'
                and not self.pqn_sent
                and self.picking_id
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
            and c.picking_id and c.measure_on == 'move_line')
        if not line_checks:
            return super().do_fail()
        first = line_checks[0]
        return {
            'name': _('Quality Check Failed'),
            'type': 'ir.actions.act_window',
            'res_model': 'quality.check.wizard',
            'view_mode': 'form',
            'views': [(self.env.ref(
                'quality_control.quality_check_wizard_form_failure').id,
                'form')],
            'target': 'new',
            'context': dict(
                self.env.context,
                default_check_ids=line_checks.ids,
                default_current_check_id=first.id,
                default_qty_tested=first.qty_to_test
                or first.move_line_id.quantity or 1,
                from_failure_form=True,
                hide_back_button=True),
        }
