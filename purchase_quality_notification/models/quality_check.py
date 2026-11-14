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

    def do_fail(self):
        # Failure handling may move the failed quantity to the failure
        # location via internal quantity writes — exempt them.
        self = self.with_context(qc_gate_off=True)
        return super().do_fail()

    def write(self, vals):
        # Capture the approvable credit before state flips to 'pass':
        # qty_tested when the operator tested a fraction, else qty_to_test
        # (the remaining demand still awaiting approval).
        credit = {}
        if vals.get('quality_state') == 'pass':
            for check in self:
                credit[check.id] = check.qty_tested or check.qty_to_test
        res = super().write(vals)
        for check in self:
            line = check.move_line_id
            if not (credit.get(check.id) and line
                    and line._is_quality_controlled_receipt_line()):
                continue
            if not check.qty_tested:
                check.qty_tested = credit[check.id]
            if line.state not in ('done', 'cancel'):
                line.quantity += credit[check.id]
        return res
