# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    tolerance_request_ids = fields.One2many(
        'purchase.tolerance.request', 'order_id',
        string='Tolerans Talepleri', readonly=True, copy=False)
    tolerance_request_count = fields.Integer(
        compute='_compute_tolerance_request_count')

    @api.depends('tolerance_request_ids')
    def _compute_tolerance_request_count(self):
        for order in self:
            order.tolerance_request_count = len(order.tolerance_request_ids)

    def action_view_tolerance_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tolerans Talepleri'),
            'res_model': 'purchase.tolerance.request',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }
