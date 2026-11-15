# -*- coding: utf-8 -*-
from odoo import api, models


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _is_quality_controlled_receipt_line(self):
        return (
            self.picking_code == 'incoming'
            and self.product_id.product_tmpl_id.quality_purchase_ok
            and not self.location_dest_id.is_failure_location
        )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # Re-attach a pending check that lost its line (e.g. the user
        # zeroed the quantity and Odoo dropped the line) when a new
        # line appears for the same product on the same picking.
        Check = self.env['quality.check']
        for line in lines:
            if line.state in ('done', 'cancel'):
                continue
            detached = Check.search([
                ('picking_id', '=', line.picking_id.id),
                ('product_id', '=', line.product_id.id),
                ('measure_on', '=', 'move_line'),
                ('move_line_id', '=', False),
                ('quality_state', '=', 'none'),
            ], limit=1)
            if detached:
                existing = line.check_ids.filtered(
                    lambda c: c.quality_state == 'none'
                    and c.product_id == detached.product_id)[:1]
                if existing:
                    # The new line already got a check from the quality
                    # point — carry the sent state over instead of
                    # attaching a duplicate.
                    existing.pqn_sent = (
                        existing.pqn_sent or detached.pqn_sent)
                    detached.unlink()
                else:
                    detached.move_line_id = line.id
        return lines

    def unlink(self):
        # Odoo deletes zero-quantity lines (user edits "Miktar" to 0, or
        # the backorder split rebuilds lines) and the quality module
        # removes the pending checks on them. Detach the check first so
        # it survives on the picking and can follow the new line —
        # the warehouse user already sent it to quality.
        pending = self.env['quality.check'].search([
            ('move_line_id', 'in', self.ids),
            ('quality_state', '=', 'none'),
        ])
        if pending:
            pending.move_line_id = False
        return super().unlink()
