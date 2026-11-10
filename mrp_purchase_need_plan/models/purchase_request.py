# -*- coding: utf-8 -*-
from odoo import models


class PurchaseRequest(models.Model):
    _inherit = "purchase.request"

    # approval state feeds the plan's PR column — a state write must
    # refresh the cached plan just like request-line writes do
    def write(self, vals):
        res = super().write(vals)
        if "state" in vals:
            self.env["mrp.purchase.need"]._bump_plan_version()
        return res
