# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseRequestLine(models.Model):
    _inherit = "purchase.request.line"

    # BRD §7.3 — traceability between the merged request line and the raw
    # material moves (needs) it consolidates. Need dates are kept on the
    # moves themselves, so they survive the merge untouched.
    need_move_ids = fields.Many2many(
        comodel_name="stock.move",
        relation="purchase_request_line_need_move_rel",
        column1="purchase_request_line_id",
        column2="move_id",
        string="Malzeme İhtiyaç Hareketleri",
        copy=False,
        readonly=True,
    )
    # links the request line to the durable MİP records it serves —
    # needed for BoM-exploded (virtual) needs that have no stock move
    need_mip_ids = fields.Many2many(
        comodel_name="mip.need.line",
        relation="purchase_request_line_need_mip_rel",
        column1="purchase_request_line_id",
        column2="mip_id",
        string="MİP Kayıtları",
        copy=False,
        readonly=True,
    )

    def _need_move_open(self):
        """Needs still attached to a live (non-cancelled / non-rejected) request."""
        return self.need_move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        )
