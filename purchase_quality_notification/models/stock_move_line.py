# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import ValidationError


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _is_quality_controlled_receipt_line(self):
        return (
            self.picking_code == 'incoming'
            and self.product_id.product_tmpl_id.quality_purchase_ok
        )

    def _quality_approved_qty(self):
        self.ensure_one()
        checks = self.env['quality.check'].search([
            ('move_line_id', '=', self.id),
            ('quality_state', '=', 'pass'),
        ])
        return sum(c.qty_tested or c.qty_to_test for c in checks)

    @api.depends('quant_id')
    def _compute_quantity(self):
        super()._compute_quantity()
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
