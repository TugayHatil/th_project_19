# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    tolerance_request_ids = fields.Many2many(
        'purchase.tolerance.request',
        'purchase_tolerance_request_move_rel',
        'move_id', 'request_id',
        string='Tolerans Talepleri')
    tolerance_state = fields.Selection(
        [('pending', 'Onay Bekliyor'),
         ('approved', 'Onaylandı'),
         ('rejected', 'Reddedildi')],
        string='Tolerans Durumu', compute='_compute_tolerance_state',
        compute_sudo=True)

    @api.depends('tolerance_request_ids.state')
    def _compute_tolerance_state(self):
        for move in self:
            requests = move.sudo().tolerance_request_ids.filtered(
                lambda r: r.state != 'cancel').sorted('id')
            move.tolerance_state = requests[-1].state if requests else False
