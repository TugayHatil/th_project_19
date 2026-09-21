# -*- coding: utf-8 -*-

from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    material_plan_line_id = fields.Many2one(
        "project.material.plan", string="Material Plan Line",
        readonly=True, index=True, ondelete="set null",
    )
