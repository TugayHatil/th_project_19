# -*- coding: utf-8 -*-
from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    revision_number = fields.Integer(string='Revision', default=0, copy=False, readonly=True)
    display_name = fields.Char(string='Reference', compute='_compute_display_name', store=True)
    was_confirmed = fields.Boolean(string="Was Confirmed", default=False)

    @api.depends('name')
    def _compute_display_name(self):
        for order in self:
            order.display_name = order.name

    def button_cancel(self):
        for order in self:
            if order.state == 'purchase':
                order.was_confirmed = True
        return super().button_cancel()

    def button_draft(self):
        for order in self:
            if order.state == 'cancel' and order.was_confirmed:
                order.revision_number += 1
            order.was_confirmed = False
        return super().button_draft()


    def write(self, vals):
        if 'revision_number' in vals:
            for order in self:
                if vals['revision_number'] > order.revision_number:
                    base_name = order.name.split('-Rev')[0]
                    vals['name'] = f"{base_name}-Rev{vals['revision_number']}"
        return super().write(vals)





