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

    def _ensure_alternative_orderpoints(self, moves):
        """Surface the shortage of a component that has alternatives on the
        replenishment screen by creating a min=0/max=0 orderpoint when none
        exists for that product/location/company.

        Odoo does not create orderpoints for MO component shortages by
        itself; the rule only makes the need visible on the replenishment
        list (and the alternative icon next to it). No procurement document
        is created automatically.
        """
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        for move in moves:
            product = move._alt_main_component()
            location = move.location_id
            company = move.company_id or self.company_id
            if Orderpoint.search_count([
                    ("product_id", "=", product.id),
                    ("location_id", "=", location.id),
                    ("company_id", "=", company.id)], limit=1):
                continue
            warehouse = move.warehouse_id or self.env["stock.warehouse"].search(
                [("lot_stock_id", "parent_of", location.id),
                 ("company_id", "=", company.id)], limit=1)
            if not warehouse:
                continue
            Orderpoint.sudo().create({
                "product_id": product.id,
                "location_id": location.id,
                "warehouse_id": warehouse.id,
                "company_id": company.id,
                "product_min_qty": 0.0,
                "product_max_qty": 0.0,
                "trigger": "auto",
            })

    def action_confirm(self):
        result = super().action_confirm()
        if len(self) == 1 and not self.env.context.get(
                "skip_alternative_check"):
            needy_moves = self._moves_needing_alternative()
            if needy_moves:
                self._ensure_alternative_orderpoints(needy_moves)
                if (self.state in ("confirmed", "progress", "to_close")
                        and self.env.user.has_group(
                            "mrp_component_alternative"
                            ".group_alternative_selector")):
                    return self.action_open_alternative_selector()
        return result
