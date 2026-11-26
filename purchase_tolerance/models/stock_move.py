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
         ('conditional', 'Koşullu'),
         ('rejected', 'Reddedildi')],
        string='Tolerans Durumu', compute='_compute_tolerance_state',
        compute_sudo=True)
    is_tolerance_excess_move = fields.Boolean(
        string='Tolerans Dışı Hareket', readonly=True, copy=False,
        help="Koşullu onay sonrası tolerans dışı miktar için iade edilecek "
             "konuma yönlendirilen hareket.")

    @api.depends('tolerance_request_ids.state')
    def _compute_tolerance_state(self):
        for move in self:
            requests = move.tolerance_request_ids.filtered(
                lambda r: r.state != 'cancel').sorted('id')
            move.tolerance_state = requests[-1].state if requests else False
