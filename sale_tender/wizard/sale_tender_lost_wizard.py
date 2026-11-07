# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleTenderLostWizard(models.TransientModel):
    _name = 'sale.tender.lost.wizard'
    _description = 'İhale Kayıt Nedeni'

    tender_id = fields.Many2one(
        'sale.tender', string='İhale', required=True, readonly=True)
    lost_reason_id = fields.Many2one(
        'sale.tender.lost.reason', string='Kayıt Nedeni', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.tender_id.write({
            'state': 'lost',
            'lost_reason_id': self.lost_reason_id.id,
        })
        return {'type': 'ir.actions.act_window_close'}
