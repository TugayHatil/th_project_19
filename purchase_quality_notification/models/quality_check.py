# -*- coding: utf-8 -*-
from odoo import models


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    def do_fail(self):
        # Failing a pending receipt check from the check form must open
        # the failure dialog (failed qty + failure location) instead of
        # failing the whole quantity — the wizard's confirm_fail applies
        # the standard split. Internal calls carry our context flag (or
        # the wizard's own from_failure_form) and fail directly.
        if (self.env.context.get('pqn_skip_fail_dialog')
                or self.env.context.get('from_failure_form')):
            return super().do_fail()
        line_checks = self.filtered(
            lambda c: c.quality_state == 'none'
            and c.picking_id and c.move_line_id)
        if not line_checks:
            return super().do_fail()
        action = self.env['ir.actions.actions']._for_xml_id(
            'quality_control.action_quality_check_wizard')
        action['context'] = dict(
            self.env.context,
            default_check_ids=line_checks.ids,
            default_current_check_id=line_checks[0].id,
            default_qty_tested=line_checks[0].qty_to_test
            or line_checks[0].move_line_id.quantity or 1,
            from_failure_form=True,
        )
        return action
