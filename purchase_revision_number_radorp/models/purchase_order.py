# -*- coding: utf-8 -*-
from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    revision_number = fields.Integer(string='Revision', default=0, copy=False, readonly=True)
    display_name = fields.Char(string='Reference', compute='_compute_display_name', store=True)
    was_confirmed = fields.Boolean(string="Was Confirmed", default=False)
    unrevisioned_name = fields.Char(string='Original Reference', copy=False, readonly=True)
    current_revision_id = fields.Many2one(
        'purchase.order', string='Current Revision', copy=False, readonly=True, index=True)
    old_revision_ids = fields.One2many(
        'purchase.order', 'current_revision_id', string='Old Revisions', readonly=True,
        context={'active_test': False})
    revision_count = fields.Integer(compute='_compute_revision_count')
    active = fields.Boolean(default=True)

    @api.depends('name')
    def _compute_display_name(self):
        for order in self:
            order.display_name = order.name

    @api.depends('old_revision_ids')
    def _compute_revision_count(self):
        for order in self:
            order.revision_count = len(order.old_revision_ids)

    def button_cancel(self):
        for order in self:
            if order.state == 'purchase':
                order.was_confirmed = True
        return super().button_cancel()

    def button_draft(self):
        for order in self:
            if order.state == 'cancel' and order.was_confirmed:
                order._archive_current_revision()
                order.revision_number += 1
            order.was_confirmed = False
        return super().button_draft()

    def _archive_current_revision(self):
        self.ensure_one()
        if not self.unrevisioned_name:
            self.unrevisioned_name = self.name.split('-Rev')[0]
        return self.copy(default={
            'name': self.name,
            'state': 'cancel',
            'active': False,
            'revision_number': self.revision_number,
            'unrevisioned_name': self.unrevisioned_name,
            'current_revision_id': self.id,
            'was_confirmed': False,
            'date_order': self.date_order,
            'date_approve': self.date_approve,
            'partner_ref': self.partner_ref,
            'origin': self.origin,
            'user_id': self.user_id.id,
            'company_id': self.company_id.id,
            'old_revision_ids': [(5, 0, 0)],
        })

    def write(self, vals):
        if 'revision_number' in vals:
            for order in self:
                if vals['revision_number'] > order.revision_number:
                    base_name = order.unrevisioned_name or order.name.split('-Rev')[0]
                    vals['name'] = f"{base_name}-Rev{vals['revision_number']}"
        return super().write(vals)

    def action_view_revisions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Revisions'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.old_revision_ids.ids)],
            'context': {'active_test': False},
        }

    def action_view_current_revision(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'res_id': self.current_revision_id.id,
        }
