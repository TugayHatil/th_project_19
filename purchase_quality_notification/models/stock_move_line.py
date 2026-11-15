# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import ValidationError


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _is_quality_controlled_receipt_line(self):
        return (
            self.picking_code == 'incoming'
            and self.product_id.product_tmpl_id.quality_purchase_ok
            and not self.location_dest_id.is_failure_location
        )

    def _quality_approved_qty(self):
        self.ensure_one()
        checks = self.env['quality.check'].search([
            ('move_line_id', '=', self.id),
            ('quality_state', '=', 'pass'),
        ])
        # qty_to_test is a live compute of the line quantity (0 by design),
        # so the approved credit is qty_tested or, when left empty, the
        # move demand — a bare "Pass" approves the whole line.
        return sum(
            c.qty_tested or self.move_id.product_uom_qty for c in checks)

    def _qc_release_tested_qty(self, checks):
        # Standard Odoo splits the demand from the quantity present on the
        # line at fail time; on gated lines that quantity is 0, which makes
        # the split produce demand=0 failure moves and strand the surviving
        # quantity. Temporarily restore the tested quantity so the split
        # sees the standard input; callers re-clamp afterwards.
        for line in self:
            tested = max(checks.filtered(
                lambda c, l=line: c.move_line_id == l
            ).mapped('qty_tested') or [0.0])
            if line.product_uom_id.compare(line.quantity, tested) < 0:
                line.with_context(qc_gate_off=True).quantity = tested

    @api.depends('quant_id')
    def _compute_quantity(self):
        super()._compute_quantity()
        # Internal reservation / quality-flow writes handle quantities
        # themselves; the clamp (or an explicit release) decides the
        # final value afterwards.
        if self.env.context.get('qc_gate_off') or self.env.context.get(
                'qc_internal'):
            return
        for line in self:
            if line.quantity and line._is_quality_controlled_receipt_line():
                line.quantity = 0

    @api.constrains('quantity')
    def _check_quality_approved_quantity(self):
        if self.env.context.get('qc_gate_off'):
            return
        for line in self:
            if (line.quantity and line.state not in ('done', 'cancel')
                    and line._is_quality_controlled_receipt_line()):
                approved = line._quality_approved_qty()
                if line.product_uom_id.compare(line.quantity, approved) > 0:
                    raise ValidationError(_(
                        '"%(product)s" için kalite kontrol onayı olmadan '
                        'kabul miktarı artırılamaz. Onaylanan miktar: '
                        '%(approved)g %(uom)s.',
                        product=line.product_id.display_name,
                        approved=approved,
                        uom=line.product_uom_id.name))
