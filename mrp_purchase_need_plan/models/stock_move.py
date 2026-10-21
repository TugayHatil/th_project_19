# -*- coding: utf-8 -*-
from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    # BRD §7.3 — inverse side of purchase.request.line.need_move_ids.
    # A raw material move linked here has already been transferred to a
    # purchase request and must not be requested again (BRD §7.2 dedup).
    purchase_need_request_line_ids = fields.Many2many(
        comodel_name="purchase.request.line",
        relation="purchase_request_line_need_move_rel",
        column1="move_id",
        column2="purchase_request_line_id",
        string="Purchase Request Lines",
        copy=False,
        readonly=True,
    )
