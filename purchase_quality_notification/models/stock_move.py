# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    quality_send_ok = fields.Boolean(
        string='Kaliteye Gönder', copy=True,
        help='Kaliteye Gönder butonuna basıldığında bu satırın kontrolü '
             'kalite ekibine iletilir.')
    quality_purchase_ok = fields.Boolean(
        related='product_id.product_tmpl_id.quality_purchase_ok')
    quality_check_state = fields.Selection(
        selection=[
            ('no_checks', 'Kontrol Yok'),
            ('not_sent', 'Kaliteye Gönderilmedi'),
            ('in_progress', 'Yapılacak Kontroller Var'),
            ('pass', 'Tüm Kontroller Geçti'),
            ('fail', 'Başarısız Kontrol Var'),
        ],
        string='Kalite Kontrol', compute='_compute_quality_check_state')
    @api.depends('move_line_ids.check_state',
                 'move_line_ids.check_ids.pqn_sent',
                 'check_id.quality_state', 'check_id.pqn_sent')
    def _compute_quality_check_state(self):
        for move in self:
            states = set(move.move_line_ids.mapped('check_state'))
            states.discard('no_checks')
            checks = move.move_line_ids.check_ids | move.check_id
            check_states = set(checks.mapped('quality_state'))
            pending = checks.filtered(
                lambda c: c.quality_state == 'none')
            if 'fail' in states or 'fail' in check_states:
                move.quality_check_state = 'fail'
            elif 'in_progress' in states or pending:
                move.quality_check_state = (
                    'in_progress'
                    if any(c.pqn_sent for c in pending)
                    else 'not_sent')
            elif states or check_states:
                move.quality_check_state = 'pass'
            else:
                move.quality_check_state = 'no_checks'

    def _pqn_send_quality_checks(self):
        # Send the flagged moves' pending checks to quality; create a
        # check only when none exists (e.g. the product was flagged
        # after confirmation). Created checks are linked to the
        # product's auto quality point so the standard failure-location
        # flow applies.
        Check = self.env['quality.check']
        test_type = self.env['quality.point.test_type'].search(
            [('technical_name', '=', 'passfail')], limit=1)
        team = self.env['quality.alert.team'].search([], limit=1)
        fail_loc = self.env['stock.location'].search(
            [('is_failure_location', '=', True),
             ('usage', '=', 'internal')], limit=1)
        sent = Check
        for move in self:
            lines = move.move_line_ids.filtered(
                lambda l: l.state not in ('done', 'cancel'))
            # Increasing the quantity after confirmation adds a
            # second move line (e.g. 100 + 5) and Odoo creates a
            # check per line. Merge lines that share the same lot
            # so both the transfer and the quality list show a
            # single line with the full quantity; serial-tracked
            # products keep one line per serial number.
            for lot_key in set(lines.mapped(
                    lambda l: l.lot_id.id or 0)):
                group = lines.filtered(
                    lambda l: (l.lot_id.id or 0) == lot_key)
                if len(group) > 1:
                    keep = group.sorted(
                        key=lambda l: l.quantity, reverse=True)[0]
                    keep.quantity = sum(group.mapped('quantity'))
                    (group - keep).unlink()
            lines = lines.exists()
            pending = Check.search([
                ('picking_id', '=', move.picking_id.id),
                ('product_id', '=', move.product_id.id),
                ('quality_state', '=', 'none'),
                '|', ('move_line_id', 'in', lines.ids),
                ('move_line_id', '=', False)])
            if pending:
                # After the line merge each lot has one line; keep
                # a single pending check per surviving line and
                # reattach the checks the removed lines left
                # detached. Detached leftovers with no free line
                # are duplicates — drop them so no zero-quantity
                # rows reach the quality list.
                merged = Check
                for line in lines:
                    group = pending.filtered(
                        lambda c: c.move_line_id == line)
                    if group:
                        (group[1:]).unlink()
                        merged |= group[0]
                detached = pending.exists().filtered(
                    lambda c: not c.move_line_id)
                for check in detached:
                    free = lines.filtered(
                        lambda l: l not in merged.mapped(
                            'move_line_id'))[:1]
                    if free:
                        check.move_line_id = free.id
                        merged |= check
                    else:
                        check.unlink()
                unsent = merged.filtered(lambda c: not c.pqn_sent)
                unsent.pqn_sent = True
                sent |= unsent
                continue
            point = self.env['quality.point'].with_context(
                active_test=False).search(
                    [('auto_purchase_tmpl_id', '=',
                      move.product_id.product_tmpl_id.id)], limit=1)
            base = {
                'point_id': point.id,
                'test_type_id': (point.test_type_id or test_type).id,
                'team_id': (point.team_id or team).id,
                'picking_id': move.picking_id.id,
                'product_id': move.product_id.id,
                'company_id': move.company_id.id,
                'failure_location_id': (
                    point.failure_location_ids[:1] or fail_loc).id,
                'pqn_sent': True,
            }
            sent |= Check.create(
                dict(base, measure_on='move_line',
                     move_line_id=lines[0].id if lines else False))
        return sent
