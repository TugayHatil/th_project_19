# -*- coding: utf-8 -*-
from odoo import api, models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.order_id._check_approval_amount_change()
        return lines

    def write(self, vals):
        res = super().write(vals)
        self.order_id._check_approval_amount_change()
        return res

    def unlink(self):
        orders = self.order_id
        res = super().unlink()
        orders._check_approval_amount_change()
        return res
