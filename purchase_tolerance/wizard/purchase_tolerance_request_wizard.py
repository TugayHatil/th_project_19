# -*- coding: utf-8 -*-
from odoo import _, api, Command, fields, models


class PurchaseToleranceRequestWizard(models.TransientModel):
    _name = 'purchase.tolerance.request.wizard'
    _description = 'Purchase Tolerance Request Wizard'

    picking_ids = fields.Many2many('stock.picking', readonly=True)
    line_ids = fields.One2many(
        'purchase.tolerance.request.wizard.line', 'wizard_id',
        string='Toleransı Aşan Satırlar')

    @api.model
    def create_from_exceeded(self, pickings, exceeded_lines):
        return self.create({
            'picking_ids': [Command.set(pickings.ids)],
            'line_ids': [
                Command.create({
                    'picking_id': data['picking'].id,
                    'order_id': data['order_line'].order_id.id,
                    'order_line_id': data['order_line'].id,
                    'ordered_qty': data['ordered_qty'],
                    'received_qty': data['received_qty'],
                    'incoming_qty': data['incoming_qty'],
                    'current_tolerance': data['current_tolerance'],
                    'max_accepted_qty': data['max_accepted_qty'],
                    'requested_tolerance': data['requested_tolerance'],
                })
                for data in exceeded_lines
            ],
        })

    def _get_open_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Satınalma Toleransı Aşıldı'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_create_requests(self):
        self.ensure_one()
        Request = self.env['purchase.tolerance.request']
        requests = Request.browse()
        for line in self.line_ids:
            existing = Request.search([
                ('order_line_id', '=', line.order_line_id.id),
                ('state', '=', 'pending'),
            ], limit=1)
            if existing:
                requests |= existing
                continue
            moves = line.picking_id.move_ids.filtered(
                lambda m: m.purchase_line_id == line.order_line_id)
            request = Request.create({
                'order_id': line.order_id.id,
                'order_line_id': line.order_line_id.id,
                'picking_id': line.picking_id.id,
                'move_ids': [Command.set(moves.ids)],
                'ordered_qty': line.ordered_qty,
                'received_qty': line.received_qty,
                'incoming_qty': line.incoming_qty,
                'current_tolerance': line.current_tolerance,
                'requested_tolerance': line.requested_tolerance,
            })
            request.sudo()._schedule_review_activity()
            request.order_id.sudo().message_post(body=_(
                '%(name)s numaralı tolerans aşımı talebi oluşturuldu.',
                name=request._get_html_link()))
            if request.picking_id:
                request.picking_id.sudo().message_post(body=_(
                    '%(name)s numaralı tolerans aşımı talebi oluşturuldu; '
                    'satınalma sorumlusunun onayı bekleniyor.',
                    name=request._get_html_link()))
            requests |= request

        action = {
            'type': 'ir.actions.act_window',
            'name': _('Tolerans Talepleri'),
            'res_model': 'purchase.tolerance.request',
            'domain': [('id', 'in', requests.ids)],
        }
        if len(requests) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': requests.id,
            })
        else:
            action['view_mode'] = 'list,form'
        return action


class PurchaseToleranceRequestWizardLine(models.TransientModel):
    _name = 'purchase.tolerance.request.wizard.line'
    _description = 'Purchase Tolerance Request Wizard Line'

    wizard_id = fields.Many2one(
        'purchase.tolerance.request.wizard', required=True, ondelete='cascade')
    picking_id = fields.Many2one('stock.picking', string='Mal Kabul', readonly=True)
    order_id = fields.Many2one('purchase.order', string='Satınalma Siparişi', readonly=True)
    order_line_id = fields.Many2one('purchase.order.line', string='PO Satırı', readonly=True)
    product_id = fields.Many2one(related='order_line_id.product_id', string='Ürün')
    uom_id = fields.Many2one(related='order_line_id.product_uom_id', string='Birim')

    ordered_qty = fields.Float(string='Sipariş Miktarı', digits='Product Unit', readonly=True)
    received_qty = fields.Float(string='Önceki Kabul', digits='Product Unit', readonly=True)
    incoming_qty = fields.Float(string='Gelen Miktar', digits='Product Unit', readonly=True)
    current_tolerance = fields.Float(string='Mevcut Tolerans (%)', digits='Discount', readonly=True)
    max_accepted_qty = fields.Float(string='Maks. Kabul', digits='Product Unit', readonly=True)
    excess_qty = fields.Float(
        string='Tolerans Dışı Miktar', digits='Product Unit',
        compute='_compute_excess_qty')
    requested_tolerance = fields.Float(
        string='Talep Edilen Tolerans (%)', digits='Discount', required=True)

    @api.depends('received_qty', 'incoming_qty', 'max_accepted_qty')
    def _compute_excess_qty(self):
        for line in self:
            line.excess_qty = max(
                line.received_qty + line.incoming_qty
                - line.max_accepted_qty, 0.0)
