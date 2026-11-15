# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    quality_send_ok = fields.Boolean(
        string='Kaliteye Gönder', copy=True,
        help='Kaliteye Gönder butonuna basıldığında bu satır için kalite '
             'kontrolü oluşturulur.')
    quality_purchase_ok = fields.Boolean(
        related='product_id.product_tmpl_id.quality_purchase_ok')
    quality_check_state = fields.Selection(
        selection=[
            ('no_checks', 'Kontrol Yok'),
            ('in_progress', 'Yapılacak Kontroller Var'),
            ('pass', 'Tüm Kontroller Geçti'),
            ('fail', 'Başarısız Kontrol Var'),
        ],
        string='Kalite Kontrol', compute='_compute_quality_check_state')

    @api.depends('move_line_ids.check_state', 'check_id.quality_state')
    def _compute_quality_check_state(self):
        for move in self:
            states = set(move.move_line_ids.mapped('check_state'))
            states.discard('no_checks')
            check_states = set(move.check_id.mapped('quality_state'))
            if 'fail' in states or 'fail' in check_states:
                move.quality_check_state = 'fail'
            elif 'in_progress' in states or 'none' in check_states:
                move.quality_check_state = 'in_progress'
            elif states or check_states:
                move.quality_check_state = 'pass'
            else:
                move.quality_check_state = 'no_checks'

    def _pqn_create_quality_checks(self):
        # Manual quality checks for the lines the warehouse user flagged
        # with "Kaliteye Gönder" — one move_line check per open line, or a
        # product-level check when the move has no lines yet. Lines that
        # already have a pending check are skipped. (Name kept distinct
        # from the standard stock.move._create_quality_checks hook.)
        Check = self.env['quality.check']
        test_type = self.env['quality.point.test_type'].search(
            [('technical_name', '=', 'passfail')], limit=1)
        team = self.env['quality.alert.team'].search([], limit=1)
        fail_loc = self.env['stock.location'].search(
            [('is_failure_location', '=', True),
             ('usage', '=', 'internal')], limit=1)
        created = Check
        for move in self:
            base = {
                'test_type_id': test_type.id,
                'team_id': team.id,
                'picking_id': move.picking_id.id,
                'product_id': move.product_id.id,
                'company_id': move.company_id.id,
                'failure_location_id': fail_loc.id,
            }
            lines = move.move_line_ids.filtered(
                lambda l: l.state not in ('done', 'cancel'))
            if not lines:
                if not Check.search_count([
                        ('picking_id', '=', move.picking_id.id),
                        ('product_id', '=', move.product_id.id),
                        ('quality_state', '=', 'none')]):
                    created |= Check.create(
                        dict(base, measure_on='product'))
                continue
            for line in lines:
                if Check.search_count([
                        ('move_line_id', '=', line.id),
                        ('quality_state', '=', 'none')]):
                    continue
                created |= Check.create(
                    dict(base, measure_on='move_line', move_line_id=line.id))
        return created
