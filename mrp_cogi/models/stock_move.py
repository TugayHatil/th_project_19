# -*- coding: utf-8 -*-
from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    cogi_record_id = fields.Many2one('mrp.cogi.record', string='COGI Kaydı',
                                     readonly=True, index=True, copy=False,
                                     ondelete='set null')
