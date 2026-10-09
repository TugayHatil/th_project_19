# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools import float_compare


class MrpAlternativeSelector(models.TransientModel):
    _name = "mrp.alternative.selector"
    _description = "Alternative Component Selector"

    mode = fields.Selection(
        [("production", "Manufacturing Order"),
         ("orderpoint", "Replenishment")], readonly=True)
    production_id = fields.Many2one("mrp.production", readonly=True)
    orderpoint_id = fields.Many2one("stock.warehouse.orderpoint", readonly=True)
    product_id = fields.Many2one("product.product", readonly=True)
    location_id = fields.Many2one("stock.location", readonly=True)
    demand_qty = fields.Float(readonly=True, digits="Product Unit")
    warning_message = fields.Text(readonly=True)
    user_can_apply = fields.Boolean(
        compute="_compute_user_can_apply", compute_sudo=True)
    line_ids = fields.One2many(
        "mrp.alternative.selector.line", "selector_id", string="Options")
    move_line_ids = fields.One2many(
        "mrp.alternative.selector.move", "selector_id",
        string="Related Manufacturing Orders")
    has_move_lines = fields.Boolean(readonly=True)
    folded_move_ids = fields.Many2many("stock.move", readonly=True)

    def _compute_user_can_apply(self):
        allowed = self.env.user.has_group(
            "mrp_component_alternative.group_alternative_selector")
        for wizard in self:
            wizard.user_can_apply = allowed

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _available_qty(self, product, location):
        return self.env["stock.quant"]._get_available_quantity(
            product, location)

    def _open_action(self, name):
        view = self.env.ref(
            "mrp_component_alternative.mrp_alternative_selector_form")
        return {
            "name": name,
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "view_id": view.id,
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Manufacturing order mode
    # ------------------------------------------------------------------
    @api.model
    def _open_for_production(self, production, move=None):
        moves = (move or production.move_raw_ids).filtered(
            lambda m: m.has_bom_alternatives
            and m.state not in ("done", "cancel"))
        wizard = self.create({
            "mode": "production",
            "production_id": production.id,
            "location_id": production.location_src_id.id,
        })
        wizard.folded_move_ids = [Command.set(moves.ids)]
        line_vals = []
        for index, mv in enumerate(moves, start=1):
            line_vals += wizard._prepare_move_lines(
                mv, index * 1000, collapsed=True)
        wizard.line_ids = [Command.create(vals) for vals in line_vals]
        wizard._refresh_warning()
        return wizard._open_action(
            _("Alternative Components - %s", production.name))

    def _rebuild_lines(self):
        """Regenerate option rows honouring the folded state of each move.

        The product currently selected (or preselected) for each move is
        remembered on the always-visible main row so folding a group never
        loses the user's selection.
        """
        remembered = {}
        for line in self.line_ids.filtered("is_original"):
            if line.remembered_selected_id:
                remembered[line.move_id.id] = line.remembered_selected_id.id
        for line in self.line_ids.filtered("selected"):
            remembered[line.move_id.id] = line.alternative_product_id.id
        moves = self.line_ids.filtered(
            "is_original").sorted("sequence").move_id
        line_vals = []
        for index, mv in enumerate(moves, start=1):
            line_vals += self._prepare_move_lines(
                mv, index * 1000,
                collapsed=mv in self.folded_move_ids,
                remembered=remembered.get(mv.id))
        self.write({
            "line_ids": [Command.clear()] + [
                Command.create(vals) for vals in line_vals]})
        self._refresh_warning()

    def _prepare_move_lines(self, move, seq_base, collapsed=False,
                            remembered=None):
        main = move._alt_main_component()
        location = move.location_id
        own_reserved = move._alt_own_reserved_qty()
        demand_main_uom = move.product_uom._compute_quantity(
            move.product_uom_qty, main.uom_id)
        main_coverage = move._alt_coverage(main, location, own_reserved)
        main_ok = float_compare(
            main_coverage, demand_main_uom,
            precision_rounding=main.uom_id.rounding) >= 0

        alternatives = move.bom_line_id.alternative_ids.filtered(
            "active").sorted("sequence")
        suggested = False
        suggested_name = ""
        alt_vals = []
        for index, alternative in enumerate(alternatives, start=1):
            product = alternative.alternative_product_id
            coverage = move._alt_coverage(product, location, own_reserved)
            # demand_main_uom is expressed in the main component's uom;
            # convert it to this product's uom (the uom category match is
            # enforced by a constraint on the alternative definition)
            demand = main.uom_id._compute_quantity(
                demand_main_uom, product.uom_id)
            can_cover = float_compare(
                coverage, demand,
                precision_rounding=product.uom_id.rounding) >= 0
            is_suggested = (not main_ok and not suggested
                            and can_cover and not move.is_alternative_component)
            if is_suggested:
                suggested_name = product.display_name
            suggested = suggested or is_suggested
            alt_vals.append({
                "move_id": move.id,
                "product_id": main.id,
                "alternative_id": alternative.id,
                "alternative_product_id": product.id,
                "sequence": seq_base + index,
                "priority": alternative.sequence,
                "demand_qty": demand,
                "uom_id": product.uom_id.id,
                "available_qty": coverage,
                "can_cover": can_cover,
                "is_suggested": is_suggested,
                "is_current": move.product_id == product,
            })

        if remembered:
            chosen = remembered
        elif move.is_alternative_component:
            chosen = move.product_id.id
        elif not main_ok and suggested:
            suggested_val = [v for v in alt_vals if v["is_suggested"]]
            chosen = suggested_val[0]["alternative_product_id"]
        else:
            chosen = main.id
        main_vals = {
            "move_id": move.id,
            "product_id": main.id,
            "demand_qty": demand_main_uom,
            "uom_id": main.uom_id.id,
            "alternative_product_id": main.id,
            "sequence": seq_base,
            "priority": 0,
            "available_qty": main_coverage,
            "can_cover": main_ok,
            "is_suggested": False,
            "is_original": True,
            "is_current": move.product_id == main,
            "alt_count": len(alternatives),
            "remembered_selected_id": chosen,
            "suggested_label": suggested_name,
            "selected": chosen == main.id,
        }
        if collapsed:
            return [main_vals]
        for vals in alt_vals:
            vals["selected"] = vals["alternative_product_id"] == chosen
        return [main_vals] + alt_vals

    # ------------------------------------------------------------------
    # Replenishment (orderpoint) mode - information only
    # ------------------------------------------------------------------
    @api.model
    def _open_for_orderpoint(self, orderpoint):
        product = orderpoint.product_id
        location = orderpoint.location_id
        demand = orderpoint.qty_to_order
        wizard = self.create({
            "mode": "orderpoint",
            "orderpoint_id": orderpoint.id,
            "product_id": product.id,
            "location_id": location.id,
            "demand_qty": demand,
        })
        alternatives = self.env["mrp.bom.line.alternative"].search([
            ("product_id", "=", product.id),
            ("active", "=", True),
            ("company_id", "in", [False, orderpoint.company_id.id]),
        ]).sorted("sequence")
        by_product = {}
        for alternative in alternatives:
            by_product.setdefault(alternative.alternative_product_id, alternative)

        # Relate the replenishment need to open manufacturing orders
        # consuming this component at the orderpoint location.
        # A substituted move is still linked through original_product_id,
        # so the option actually in use can be marked reliably.
        open_moves = self.env["stock.move"].search([
            ("raw_material_production_id", "!=", False),
            ("location_id", "child_of", location.id),
            ("company_id", "=", orderpoint.company_id.id),
            ("state", "not in", ("done", "cancel")),
            "|", ("product_id", "=", product.id),
            ("original_product_id", "=", product.id),
        ]).filtered(
            lambda m: m._alt_main_component() == product)
        in_use_products = open_moves.product_id
        wizard.move_line_ids = [Command.create({
            "move_id": move.id,
            "production_id": move.raw_material_production_id.id,
            "move_product_id": move.product_id.id,
            "demand_qty": move.product_uom._compute_quantity(
                move.product_uom_qty, move.product_id.uom_id),
            "reserved_qty": move._alt_own_reserved_qty(),
            "is_alternative": move.is_alternative_component,
            "state": move.state,
        }) for move in open_moves]
        wizard.has_move_lines = bool(open_moves)

        main_coverage = wizard._available_qty(product, location)
        main_ok = float_compare(
            main_coverage, demand,
            precision_rounding=product.uom_id.rounding) >= 0
        line_vals = [{
            "product_id": product.id,
            "alternative_product_id": product.id,
            "demand_qty": demand,
            "uom_id": product.uom_id.id,
            "available_qty": main_coverage,
            "can_cover": main_ok,
            "is_original": True,
            "is_current": product in in_use_products,
            "alt_count": len(by_product),
            "sequence": 0,
        }]
        suggested = False
        for index, (alt_product, alternative) in enumerate(
                by_product.items(), start=1):
            coverage = wizard._available_qty(alt_product, location)
            demand_alt_uom = product.uom_id._compute_quantity(
                demand, alt_product.uom_id)
            can_cover = float_compare(
                coverage, demand_alt_uom,
                precision_rounding=alt_product.uom_id.rounding) >= 0
            is_suggested = not main_ok and not suggested and can_cover
            suggested = suggested or is_suggested
            line_vals.append({
                "product_id": product.id,
                "alternative_id": alternative.id,
                "alternative_product_id": alt_product.id,
                "sequence": index,
                "priority": alternative.sequence,
                "demand_qty": demand_alt_uom,
                "uom_id": alt_product.uom_id.id,
                "available_qty": coverage,
                "can_cover": can_cover,
                "is_suggested": is_suggested,
                "is_current": alt_product in in_use_products,
            })
        wizard.line_ids = [Command.create(vals) for vals in line_vals]
        wizard._refresh_warning()
        return wizard._open_action(
            _("Alternative Components - %s", product.display_name))

    # ------------------------------------------------------------------
    # Warning message
    # ------------------------------------------------------------------
    def _refresh_warning(self):
        self.ensure_one()
        messages = []
        if self.mode == "production":
            for move in self.line_ids.move_id:
                lines = self.line_ids.filtered(lambda l: l.move_id == move)
                if not lines.filtered("can_cover"):
                    messages.append(_(
                        "%s: neither the main component nor any alternative "
                        "can fully cover the demand. Plan a purchase or "
                        "production for this component.",
                        move._alt_main_component().display_name))
                elif not lines.filtered(lambda l: l.is_original and l.can_cover):
                    suggested = lines.filtered("is_suggested")
                    messages.append(_(
                        "%s: main component stock is insufficient.%s",
                        move._alt_main_component().display_name,
                        _(" Suggested alternative: %s.",
                          suggested.alternative_product_id.display_name)
                        if suggested else ""))
        elif self.mode == "orderpoint":
            if not self.line_ids.filtered("can_cover"):
                messages.append(_(
                    "Neither the main component nor any alternative can "
                    "fully cover the demand."))
            elif not self.line_ids.filtered(
                    lambda l: l.is_original and l.can_cover):
                messages.append(_(
                    "Main component stock is insufficient; an alternative "
                    "can be used on the manufacturing order."))
        self.warning_message = "\n".join(messages)

    # ------------------------------------------------------------------
    # Apply the selection
    # ------------------------------------------------------------------
    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group(
                "mrp_component_alternative.group_alternative_selector"):
            raise UserError(_(
                "You are not allowed to select alternative components."))
        per_move = defaultdict(lambda: self.env[
            "mrp.alternative.selector.line"])
        for line in self.line_ids.filtered("move_id"):
            per_move[line.move_id] |= line
        for move, lines in per_move.items():
            selected = lines.filtered("selected")
            if len(selected) > 1:
                raise UserError(_(
                    "Only one option can be selected for component %s.",
                    move._alt_main_component().display_name))
            target = selected.alternative_product_id
            if not selected:
                # Folded group: fall back to the selection remembered on
                # the always-visible main row.
                target = lines.filtered(
                    "is_original").remembered_selected_id
            if not target or target == move.product_id:
                continue
            demand = move.product_uom._compute_quantity(
                move.product_uom_qty, target.uom_id)
            own_reserved = move._alt_own_reserved_qty()
            coverage = move._alt_coverage(
                target, move.location_id, own_reserved)
            if float_compare(
                    coverage, demand,
                    precision_rounding=target.uom_id.rounding) < 0:
                raise UserError(_(
                    "Stock for %(product)s changed: %(avail)s %(uom)s "
                    "available but %(demand)s needed for %(main)s. Please "
                    "re-evaluate the alternatives.",
                    product=target.display_name, avail=coverage,
                    uom=target.uom_id.name, demand=demand,
                    main=move._alt_main_component().display_name))
            move._apply_alternative_product(target)
        return {"type": "ir.actions.act_window_close"}


class MrpAlternativeSelectorLine(models.TransientModel):
    _name = "mrp.alternative.selector.line"
    _description = "Alternative Component Selector Line"
    _order = "sequence, id"

    selector_id = fields.Many2one(
        "mrp.alternative.selector", required=True, ondelete="cascade")
    sequence = fields.Integer(readonly=True)
    move_id = fields.Many2one("stock.move", readonly=True)
    product_id = fields.Many2one(
        "product.product", string="Main Component", readonly=True)
    alternative_id = fields.Many2one(
        "mrp.bom.line.alternative", readonly=True)
    alternative_product_id = fields.Many2one(
        "product.product", string="Option", readonly=True)
    priority = fields.Integer(readonly=True)
    demand_qty = fields.Float(
        string="Demand", readonly=True, digits="Product Unit")
    available_qty = fields.Float(
        string="Available", readonly=True, digits="Product Unit")
    uom_id = fields.Many2one("uom.uom", readonly=True)
    can_cover = fields.Boolean(string="Covers Demand", readonly=True)
    is_suggested = fields.Boolean(string="Suggested", readonly=True)
    is_current = fields.Boolean(string="In Use", readonly=True)
    is_original = fields.Boolean(string="Original", readonly=True)
    status_label = fields.Char(
        string="Status", compute="_compute_labels", readonly=True)
    component_label = fields.Char(
        compute="_compute_labels", readonly=True)
    is_folded = fields.Boolean(
        compute="_compute_is_folded", readonly=True)
    alt_count = fields.Integer(readonly=True)
    remembered_selected_id = fields.Many2one(
        "product.product", readonly=True)
    suggested_label = fields.Char(readonly=True)
    selected = fields.Boolean(string="Select")

    @api.depends("selector_id.folded_move_ids", "move_id")
    def _compute_is_folded(self):
        for line in self:
            line.is_folded = bool(
                line.move_id
                and line.move_id in line.selector_id.folded_move_ids)

    @api.depends("can_cover", "is_suggested", "is_current", "is_original",
                 "product_id", "suggested_label")
    def _compute_labels(self):
        for line in self:
            # The component name is shown only on the bold main row so
            # each block reads as one component + its options.
            line.component_label = (
                line.product_id.display_name if line.is_original else "")
            parts = []
            if line.is_current:
                parts.append(_("Kullanımda"))
            if line.is_suggested:
                parts.append(_("Önerilen"))
            if not line.can_cover:
                parts.append(_("Yetersiz Stok"))
            if line.is_original and line.suggested_label:
                parts.append(_("Önerilen: %s") % line.suggested_label)
            line.status_label = " \u00b7 ".join(parts)

    def action_toggle_fold(self):
        self.ensure_one()
        selector = self.selector_id
        move = self.move_id
        if not move:
            return True
        if move in selector.folded_move_ids:
            selector.folded_move_ids = [Command.unlink(move.id)]
        else:
            selector.folded_move_ids = [Command.link(move.id)]
        selector._rebuild_lines()
        # Reopen the same wizard so the dialog refreshes instead of closing
        return selector._open_action(
            _("Alternative Components - %s",
              selector.production_id.display_name))


class MrpAlternativeSelectorMove(models.TransientModel):
    """Open manufacturing-order demand related to a replenishment line.

    Lets the user see which MOs consume the component at this location
    and which product is actually in use on each of them.
    """
    _name = "mrp.alternative.selector.move"
    _description = "Related Manufacturing Order Demand"
    _order = "production_id, id"

    selector_id = fields.Many2one(
        "mrp.alternative.selector", required=True, ondelete="cascade")
    move_id = fields.Many2one("stock.move", readonly=True)
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", readonly=True)
    move_product_id = fields.Many2one(
        "product.product", string="Product In Use", readonly=True)
    demand_qty = fields.Float(
        string="Demand", readonly=True, digits="Product Unit")
    reserved_qty = fields.Float(
        string="Reserved", readonly=True, digits="Product Unit")
    is_alternative = fields.Boolean(string="Alternative Used", readonly=True)
    state = fields.Selection(
        related="move_id.state", string="State", readonly=True)
