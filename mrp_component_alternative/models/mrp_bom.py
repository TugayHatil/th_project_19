# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    bom_alternative_ids = fields.One2many(
        "mrp.bom.line.alternative", "bom_id",
        compute="_compute_bom_alternative_ids",
        string="Component Alternatives", compute_sudo=True)

    @api.depends("bom_line_ids")
    def _compute_bom_alternative_ids(self):
        Alternative = self.env["mrp.bom.line.alternative"]
        for bom in self:
            bom.bom_alternative_ids = Alternative.search(
                [("bom_line_id", "in", bom.bom_line_ids.ids)])
