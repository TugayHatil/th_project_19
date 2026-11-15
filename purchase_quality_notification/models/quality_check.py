# -*- coding: utf-8 -*-
from odoo import api, fields, models


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    qty_line = fields.Float(compute='_compute_qty_line_pqn')

    @api.depends('production_id.qty_producing', 'move_line_id.quantity',
                 'move_line_id.move_id.product_uom_qty')
    def _compute_qty_line_pqn(self):
        for check in self:
            ml = check.move_line_id
            if (ml and check.quality_state == 'none'
                    and ml._is_quality_controlled_receipt_line()):
                check.qty_line = max(
                    ml.move_id.product_uom_qty - ml._quality_approved_qty(), 0.0)
            elif check.production_id:
                check.qty_line = check.production_id.qty_producing
            elif ml:
                check.qty_line = ml.quantity
            else:
                check.qty_line = 0.0

    def do_pass(self):
        # Explicit user pass on a gated line credits the approved qty.
        # Internal callers (the partial-fail split path calls do_pass for
        # the surviving part) carry qc_internal and must not credit.
        ctx = {'qc_gate_off': True}
        if not self.env.context.get('qc_internal'):
            ctx['qc_user_pass'] = True
        self = self.with_context(**ctx)
        return super().do_pass()

    def do_fail(self):
        # Failure handling may move the failed quantity to the failure
        # location via internal quantity writes — exempt them.
        self = self.with_context(qc_gate_off=True, qc_internal=True)
        lines = self.move_line_id.filtered(
            '_is_quality_controlled_receipt_line')
        lines._qc_release_tested_qty(self)
        res = super().do_fail()
        lines.move_id._clamp_quality_lines()
        return res

    def write(self, vals):
        # Credit the approved quantity only for explicit user passes
        # (qc_user_pass): passes auto-created by Odoo's partial-fail split
        # must not add credit — the split already writes the good/failed
        # quantities on the move lines itself.
        if vals.get('quality_state') != 'pass' \
                or not self.env.context.get('qc_user_pass'):
            return super().write(vals)
        credit = {c.id: c.qty_tested or c.qty_to_test for c in self}
        res = super().write(vals)
        for check in self:
            line = check.move_line_id
            if not (credit.get(check.id) and line
                    and line._is_quality_controlled_receipt_line()):
                continue
            if not check.qty_tested:
                check.qty_tested = credit[check.id]
            if line.state not in ('done', 'cancel'):
                line.quantity = line._quality_approved_qty()
        return res
