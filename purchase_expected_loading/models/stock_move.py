# -*- coding: utf-8 -*-
from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    expected_loading_date = fields.Datetime(
        related='purchase_line_id.expected_loading_date',
        string='Beklenen Yükleme', store=True, readonly=False)
