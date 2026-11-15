# -*- coding: utf-8 -*-
from odoo import models


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    def _is_quality_controlled_receipt_line(self):
        return (
            self.picking_code == 'incoming'
            and self.product_id.product_tmpl_id.quality_purchase_ok
            and not self.location_dest_id.is_failure_location
        )
