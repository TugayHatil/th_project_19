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
        if production and production.is_locked:
            raise UserError(_(
                "The manufacturing order %s is locked; component products "
                "cannot be changed.", production.display_name))

    def _apply_alternative_product(self, new_product, demand=None):
        """Replace the move's product by *new_product* and re-reserve.

        Stock checks must be done by the caller; this method only performs
        the swap and keeps the traceability fields up to date.
        """
        self.ensure_one()
        self._check_alternative_allowed()
        if new_product == self.product_id:
            return
        origin = self._alt_main_component()
        if new_product.uom_id.category_id != origin.uom_id.category_id:
            raise UserError(_(
                "%(alt)s cannot replace %(main)s: incompatible units of "
                "measure.", alt=new_product.display_name,
                main=origin.display_name))
        old_product = self.product_id
        self._do_unreserve()
        self.write({
            "product_id": new_product.id,
            "name": new_product.display_name,
            "is_alternative_component": new_product != origin,
            "original_product_id": origin.id,
            "alternative_selected_by": self.env.user.id,
            "alternative_selected_date": fields.Datetime.now(),
        })
        if self.state not in ("draft", "cancel"):
            self._action_assign()
        production = self.raw_material_production_id
        if production:
            production.message_post(body=_(
                "Alternative component applied: %(old)s replaced by "
                "%(new)s (demand %(qty)s %(uom)s), selected by %(user)s.",
                old=old_product.display_name, new=new_product.display_name,
                qty=self.product_uom_qty, uom=self.product_uom.name,
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
