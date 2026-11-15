# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

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
