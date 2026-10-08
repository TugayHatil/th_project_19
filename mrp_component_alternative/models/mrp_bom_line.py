# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class MrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    alternative_ids = fields.One2many(
        "mrp.bom.line.alternative", "bom_line_id",
        string="Alternative Components")
    alternative_count = fields.Integer(
        compute="_compute_alternative_count", compute_sudo=True)

    @api.depends("alternative_ids.active")
    def _compute_alternative_count(self):
        for line in self:
            line.alternative_count = len(
                line.alternative_ids.filtered("active"))

    def action_manage_alternatives(self):
        self.ensure_one()
        view = self.env.ref(
            "mrp_component_alternative.mrp_bom_line_alternative_form")
        return {
            "name": _("Alternative Components"),
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom.line",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": view.id,
            "target": "new",
        }
