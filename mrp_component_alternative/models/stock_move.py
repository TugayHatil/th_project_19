# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare


class StockMove(models.Model):
    _inherit = "stock.move"

    has_bom_alternatives = fields.Boolean(
        compute="_compute_has_bom_alternatives", compute_sudo=True)
    is_alternative_component = fields.Boolean(
        string="Alternative Used", readonly=True, copy=False)
    original_product_id = fields.Many2one(
        "product.product", string="Original Component",
        readonly=True, copy=False)
    alternative_selected_by = fields.Many2one(
        "res.users", string="Alternative Selected By",
        readonly=True, copy=False)
    alternative_selected_date = fields.Datetime(
        string="Alternative Selected On", readonly=True, copy=False)
    is_alternative_origin = fields.Boolean(
        string="Substituted Origin", readonly=True, copy=False)
    alternative_original_qty = fields.Float(
        string="Original Demand", readonly=True, copy=False,
        digits="Product Unit")
    alt_group_id = fields.Many2one(
        "product.product", compute="_compute_alt_group", store=True,
        compute_sudo=True)
    alternative_rank = fields.Integer(
        compute="_compute_alternative_rank", compute_sudo=True)
    alternative_label = fields.Char(
        compute="_compute_alternative_rank", compute_sudo=True)
    alt_marker = fields.Char(
        compute="_compute_alternative_rank", compute_sudo=True)

    @api.depends("product_id", "original_product_id")
    def _compute_alt_group(self):
        """Sort key that keeps every alternative line next to the other
        lines of the same original component."""
        for move in self:
            move.alt_group_id = move.original_product_id or move.product_id

    @api.depends("product_id", "bom_line_id", "is_alternative_component",
                 "original_product_id")
    def _compute_alternative_rank(self):
        for move in self:
            rank = 0
            if move.is_alternative_component and move.bom_line_id:
                alternatives = move.bom_line_id.alternative_ids.filtered(
                    "active").sorted("sequence")
                for index, alternative in enumerate(alternatives, 1):
                    if alternative.alternative_product_id == move.product_id:
                        rank = index
                        break
            move.alternative_rank = rank
            if rank:
                move.alternative_label = _("Alt-%d") % rank
            elif move.original_product_id:
                move.alternative_label = _("Ana")
            else:
                move.alternative_label = ""
            move.alt_marker = "↳" if move.original_product_id else ""

    @api.depends("bom_line_id", "bom_line_id.alternative_ids.active")
    def _compute_has_bom_alternatives(self):
        for move in self:
            move.has_bom_alternatives = bool(
                move.bom_line_id.alternative_ids.filtered("active"))

    # ------------------------------------------------------------------
    # Availability helpers (all quantities expressed in product uom)
    # ------------------------------------------------------------------
    def _alt_quant_available(self, product, location):
        """Available (on-hand minus reserved) quantity of *product* at
        *location* and its children, in the product's uom."""
        return self.env["stock.quant"]._get_available_quantity(
            product, location)

    def _alt_own_reserved_qty(self):
        """Quantity of the move's current product already reserved for this
        move, in product uom."""
        self.ensure_one()
        return sum(self.move_line_ids.mapped("quantity_product_uom"))

    def _alt_main_component(self):
        """The BOM component product of this move, even after substitution."""
        self.ensure_one()
        return self.original_product_id or self.product_id

    def _alt_coverage(self, product, location, own_reserved=0.0):
        """Available coverage for *product* including the quantity already
        reserved for this move when the move currently uses *product*."""
        coverage = self._alt_quant_available(product, location)
        if product == self.product_id:
            coverage += own_reserved
        return coverage

    def _alt_can_fully_cover(self, product, location, demand, own_reserved=0.0):
        coverage = self._alt_coverage(product, location, own_reserved)
        return float_compare(
            coverage, demand,
            precision_rounding=product.uom_id.rounding) >= 0

    # ------------------------------------------------------------------
    # Substitution
    # ------------------------------------------------------------------
    def _check_alternative_allowed(self):
        self.ensure_one()
        production = self.raw_material_production_id
        if self.state in ("done", "cancel"):
            raise UserError(_(
                "The component line %s is already processed; its product "
                "cannot be changed.", self.product_id.display_name))
        if self.picked or self.move_line_ids.filtered("picked"):
            raise UserError(_(
                "The component %s has already been consumed; its product "
                "cannot be changed.", self.product_id.display_name))
        if (production and production.is_locked
                and not self.env.context.get("mrp_alt_allow_locked")):
            raise UserError(_(
                "The manufacturing order %s is locked; unlock it before "
                "changing component products.", production.display_name))

    def _placeholder_vals(self, origin, demand, now):
        """Values that turn this move into the passive original-component
        placeholder line (no demand, no reservation, kept for display)."""
        return {
            "product_id": origin.id,
            "name": origin.display_name,
            "alternative_original_qty":
                self.alternative_original_qty or demand,
            "product_uom_qty": 0.0,
            "is_alternative_component": False,
            "original_product_id": False,
            "is_alternative_origin": True,
            "alternative_selected_by": self.env.user.id,
            "alternative_selected_date": now,
        }

    def _spawn_alternative_move(self, product, qty_move_uom, origin, now):
        """Create a confirmed child move for *product* under this line."""
        new_move = self.copy({
            "product_id": product.id,
            "name": product.display_name,
            "product_uom_qty": qty_move_uom,
            "is_alternative_component": product != origin,
            "original_product_id": origin.id,
            "alternative_selected_by": self.env.user.id,
            "alternative_selected_date": now,
        })
        new_move._action_confirm(merge=False)
        if new_move.state not in ("draft", "cancel"):
            new_move._action_assign()
        return new_move

    def _apply_alternative_product(self, new_product, demand=None):
        """Replace the move's product by *new_product* and re-reserve.

        The original component line is kept as a passive zero-demand
        placeholder so the substitution stays visible on the order;
        the alternative is consumed through a new child move.

        Stock checks must be done by the caller; this method only performs
        the swap and keeps the traceability fields up to date.
        """
        self.ensure_one()
        self._check_alternative_allowed()
        origin = self._alt_main_component()
        if new_product == self.product_id and not self.is_alternative_origin:
            return
        if not origin.uom_id._has_common_reference(new_product.uom_id):
            raise UserError(_(
                "%(alt)s cannot replace %(main)s: incompatible units of "
                "measure.", alt=new_product.display_name,
                main=origin.display_name))
        old_product = self.product_id
        self._do_unreserve()
        now = fields.Datetime.now()
        production = self.raw_material_production_id
        if new_product == origin:
            # Revert: restore this line to the original component.
            self.write({
                "product_id": origin.id,
                "name": origin.display_name,
                "product_uom_qty":
                    self.alternative_original_qty or self.product_uom_qty,
                "alternative_original_qty": 0.0,
                "is_alternative_component": False,
                "original_product_id": False,
                "is_alternative_origin": False,
                "alternative_selected_by": self.env.user.id,
                "alternative_selected_date": now,
            })
            if self.state not in ("draft", "cancel"):
                self._action_assign()
            if production:
                production.message_post(body=_(
                    "Component %s reverted to the original product, "
                    "selected by %s.", origin.display_name,
                    self.env.user.name))
            return
        qty = demand if demand is not None else (
            self.alternative_original_qty or self.product_uom_qty)
        self.write(self._placeholder_vals(origin, qty, now))
        self._spawn_alternative_move(new_product, qty, origin, now)
        if production:
            production.message_post(body=_(
                "Alternative component applied: %(old)s replaced by "
                "%(new)s (demand %(qty)s %(uom)s), selected by %(user)s.",
                old=old_product.display_name, new=new_product.display_name,
                qty=qty, uom=self.product_uom.name,
                user=self.env.user.name))

    def _apply_partial_alternative(self, allocations):
        """Split this move across several products.

        *allocations* is a list of ``(product, qty)`` tuples where *qty* is
        expressed in the product's own uom. This move is kept as a passive
        zero-demand placeholder of the original component and every
        allocation is created as a confirmed child move beneath it.
        """
        self.ensure_one()
        self._check_alternative_allowed()
        origin = self._alt_main_component()
        allocations = [
            (product, qty) for product, qty in allocations
            if float_compare(
                qty, 0.0,
                precision_rounding=product.uom_id.rounding) > 0]
        if not allocations:
            return
        if len(allocations) == 1 and allocations[0][0] == origin:
            # Full coverage by the main component itself = revert.
            self._apply_alternative_product(origin)
            return
        self._do_unreserve()
        now = fields.Datetime.now()
        self.write(self._placeholder_vals(
            origin, self.product_uom_qty, now))
        parts = []
        for product, qty in allocations:
            qty_move_uom = product.uom_id._compute_quantity(
                qty, self.product_uom)
            self._spawn_alternative_move(
                product, qty_move_uom, origin, now)
            parts.append(
                "%s %.2f %s" % (product.display_name, qty, product.uom_id.name))
        production = self.raw_material_production_id
        if production:
            production.message_post(body=_(
                "Alternative components applied: %(old)s split into "
                "%(parts)s, selected by %(user)s.",
                old=origin.display_name, parts=" + ".join(parts),
                user=self.env.user.name))

    def action_open_alternative_selector(self):
        self.ensure_one()
        production = self.raw_material_production_id
        if not production:
            raise UserError(_(
                "Alternative components can only be selected on "
                "manufacturing order component lines."))
        return self.env["mrp.alternative.selector"]._open_for_production(
            production, move=self)
