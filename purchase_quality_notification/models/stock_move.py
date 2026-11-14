# -*- coding: utf-8 -*-
from odoo import models


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _qc_gated_moves(self):
        return self.filtered(
            lambda m: m.picking_type_id.code == 'incoming'
            and m.product_id.product_tmpl_id.quality_purchase_ok)

    def _clamp_quality_lines(self):
        for move in self:
            for line in move.move_line_ids.filtered(
                    lambda l: l.state not in ('done', 'cancel')):
                approved = line._quality_approved_qty()
                if line.product_uom_id.compare(line.quantity, approved) > 0:
                    line.with_context(qc_gate_off=True).quantity = approved

    def _action_confirm(self, merge=True, merge_into=False, create_proc=True):
        kk = self._qc_gated_moves()
        outer = self.env.context.get('qc_in_confirm')
        if kk and not outer:
            self = self.with_context(qc_gate_off=True, qc_in_confirm=True)
        res = super()._action_confirm(
            merge=merge, merge_into=merge_into, create_proc=create_proc)
        # When called inside picking.action_confirm the outer level clamps
        # after the quality checks snapshot the line quantity.
        if kk and not outer:
            kk._clamp_quality_lines()
        return res

    def _action_assign(self, force_qty=False):
        kk = self._qc_gated_moves()
        if kk:
            self = self.with_context(qc_gate_off=True)
        res = super()._action_assign(force_qty=force_qty)
        # During action_confirm the quality checks read the line quantity
        # when created later; the clamp is deferred to picking.action_confirm.
        if not self.env.context.get('qc_in_confirm'):
            kk._clamp_quality_lines()
        return res
