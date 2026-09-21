# -*- coding: utf-8 -*-

from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    material_plan_line_ids = fields.Many2many(
        "project.material.plan", string="Material Plan Lines",
        compute="_compute_material_plan_line_ids",
    )

    @api.depends("move_ids.material_plan_line_id")
    def _compute_material_plan_line_ids(self):
        for picking in self:
            picking.material_plan_line_ids = picking.move_ids.material_plan_line_id

    def action_open_material_plan_lines(self):
        lines = self.material_plan_line_ids
        return {
            "type": "ir.actions.act_window",
            "name": "Material Plan",
            "res_model": "project.material.plan",
            "domain": [["id", "in", lines.ids]],
            "view_mode": "list,form",
            "target": "current",
        }
