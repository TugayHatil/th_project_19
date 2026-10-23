# -*- coding: utf-8 -*-
from odoo import api, models


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    # BoM lines drive the explosion graph — component changes must
    # invalidate the cached plan immediately
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return recs

    def write(self, vals):
        res = super().write(vals)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return res

    def unlink(self):
        res = super().unlink()
        self.env["mrp.purchase.need"]._bump_plan_version()
        return res
