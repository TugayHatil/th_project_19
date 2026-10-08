# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools import float_compare


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    alternative_component_count = fields.Integer(
        compute="_compute_alternative_component_count", compute_sudo=True)
    alternative_shortage_count = fields.Integer(
        compute="_compute_alternative_component_count", compute_sudo=True)

    @api.depends("move_raw_ids.bom_line_id")
    def _compute_alternative_component_count(self):
        for production in self:
            moves = production.move_raw_ids.filtered(
                lambda m: m.has_bom_alternatives
                and m.state not in ("done", "cancel"))
            production.alternative_component_count = len(moves)
            production.alternative_shortage_count = len(moves.filtered(
                lambda m: not m.is_alternative_component
                and not m._alt_can_fully_cover(
                    m._alt_main_component(), m.location_id,
                    m.product_uom._compute_quantity(
                        m.product_uom_qty, m.product_id.uom_id),
                    m._alt_own_reserved_qty())))

    def _moves_needing_alternative(self):
        self.ensure_one()
        return self.move_raw_ids.filtered(
            lambda m: m.has_bom_alternatives
            and not m.is_alternative_component
            and m.state not in ("done", "cancel")
            and not m._alt_can_fully_cover(
                m._alt_main_component(), m.location_id,
                m.product_uom._compute_quantity(
                    m.product_uom_qty, m.product_id.uom_id),
                m._alt_own_reserved_qty()))

    def action_open_alternative_selector(self):
        self.ensure_one()
        return self.env["mrp.alternative.selector"]._open_for_production(self)

    def action_confirm(self):
        result = super().action_confirm()
        if (len(self) == 1
                and not self.env.context.get("skip_alternative_check")
                and self.state in ("confirmed", "progress", "to_close")
                and self.env.user.has_group(
                    "mrp_component_alternative.group_alternative_selector")
                and self._moves_needing_alternative()):
            return self.action_open_alternative_selector()
        return result
