# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProjectMaterialPlan(models.Model):
    """Material planning lines for a project (BRD: Material Plan → Stock).

    Each line links a real ``product.product`` to a Task/WBS of the same
    project, carries its own source/destination stock locations (defaulted
    from the project) and lives in a two-step lifecycle:

        draft  ──approve──▶  approved → stock.picking / stock.move

    Approval groups lines by (project, source, destination) and creates one
    standard Odoo ``stock.picking`` per group with one ``stock.move`` per
    line. Everything after that — reservation, shortage, replenishment,
    purchase, MRP — is standard Odoo; this addon deliberately does not
    reimplement any of it. Approved lines are read-only: a new need is a
    new draft line, never a quantity edit on an approved one.
    """

    _name = "project.material.plan"
    _description = "Project Material Plan"
    _order = "project_id, task_id, product_id, id"

    project_id = fields.Many2one(
        "project.project", string="Project", required=True, index=True,
        ondelete="cascade",
    )
    task_id = fields.Many2one(
        "project.task", string="Task / WBS", required=True, index=True,
        ondelete="cascade",
        domain="[('project_id', '=', project_id)]",
    )
    product_id = fields.Many2one(
        "product.product", string="Product", required=True, index=True,
        ondelete="restrict",
        domain="[('is_storable', '=', True)]",
    )
    description = fields.Char(string="Description")
    planned_quantity = fields.Float(
        string="Quantity", required=True, default=1.0,
    )
    uom_id = fields.Many2one(
        "uom.uom", string="UoM", required=True,
        compute="_compute_uom_id", store=True, readonly=False,
    )
    required_date = fields.Date(
        string="Required Date", required=True,
        compute="_compute_required_date", store=True, readonly=False,
    )
    source_location_id = fields.Many2one(
        "stock.location", string="Source Location", required=True,
        compute="_compute_locations", store=True, readonly=False,
        domain="[('usage', '=', 'internal')]",
    )
    destination_location_id = fields.Many2one(
        "stock.location", string="Destination Location", required=True,
        compute="_compute_locations", store=True, readonly=False,
        domain="[('usage', '=', 'internal')]",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved")],
        string="Status", default="draft", required=True, readonly=True,
        index=True,
    )
    # Material Plan → stock.move → stock.picking. One line may map to more
    # than one move/picking in a later phase, so the link is 1-N.
    move_ids = fields.One2many(
        "stock.move", "material_plan_line_id", string="Stock Moves",
        readonly=True,
    )
    picking_ids = fields.Many2many(
        "stock.picking", string="Transfers",
        compute="_compute_picking_ids",
    )
    # First transfer as a clickable M2O — the list column links straight
    # into the standard stock.picking form (BRD: UI navigation).
    picking_id = fields.Many2one(
        "stock.picking", string="Transfer",
        compute="_compute_picking_ids",
    )
    picking_count = fields.Integer(
        string="Transfer Count", compute="_compute_picking_ids",
    )
    notes = fields.Text(string="Notes")
    company_id = fields.Many2one(
        "res.company", string="Company",
        related="project_id.company_id", store=True,
    )
    currency_id = fields.Many2one(
        "res.currency", string="Currency",
        related="company_id.currency_id",
    )
    unit_cost = fields.Float(
        string="Unit Cost", related="product_id.standard_price", readonly=True,
    )
    planned_cost = fields.Monetary(
        string="Planned Cost", currency_field="currency_id",
        compute="_compute_planned_cost",
    )
    parent_task_id = fields.Many2one(
        "project.task", string="WBS / Parent",
        related="task_id.parent_id", store=True,
    )
    wbs_code = fields.Char(related="task_id.wbs_code", store=True)

    @api.depends("task_id", "product_id")
    def _compute_display_name(self):
        for line in self:
            parts = [p for p in (line.task_id.display_name, line.product_id.display_name) if p]
            line.display_name = " — ".join(parts) or _("Material Plan Line")

    @api.depends("product_id")
    def _compute_uom_id(self):
        for line in self:
            if line.product_id:
                line.uom_id = line.product_id.uom_id

    @api.depends("task_id.date_deadline")
    def _compute_required_date(self):
        for line in self:
            if not line.required_date:
                deadline = line.task_id.date_deadline
                line.required_date = deadline.date() if deadline else False

    @api.depends("project_id.material_source_location_id",
                 "project_id.material_destination_location_id")
    def _compute_locations(self):
        Location = self.env["stock.location"]
        for line in self:
            # Existing rows (upgrade) get a sane internal-location fallback
            # when the project has no defaults configured yet.
            fallback = Location.search([
                ("usage", "=", "internal"),
                ("company_id", "in", [line.company_id.id, False]),
            ], limit=1)
            if not line.source_location_id:
                line.source_location_id = (
                    line.project_id.material_source_location_id or fallback)
            if not line.destination_location_id:
                line.destination_location_id = (
                    line.project_id.material_destination_location_id or fallback)

    @api.depends("planned_quantity", "product_id.standard_price")
    def _compute_planned_cost(self):
        for line in self:
            line.planned_cost = line.planned_quantity * (line.unit_cost or 0.0)

    @api.depends("move_ids.picking_id")
    def _compute_picking_ids(self):
        for line in self:
            pickings = line.move_ids.picking_id
            line.picking_ids = pickings
            line.picking_id = pickings[:1]
            line.picking_count = len(pickings)

    @api.model_create_multi
    def create(self, vals_list):
        """Fill editable defaults deterministically — the compute-based
        defaults only cover form/onchange flows; programmatic creates
        (RPC, import, server actions) get them here."""
        for vals in vals_list:
            product = self.env["product.product"].browse(vals.get("product_id"))
            if product and not vals.get("uom_id"):
                vals["uom_id"] = product.uom_id.id
            task = self.env["project.task"].browse(vals.get("task_id"))
            if task and not vals.get("required_date"):
                deadline = task.date_deadline
                vals["required_date"] = deadline.date() if deadline else fields.Date.today()
            project = self.env["project.project"].browse(vals.get("project_id"))
            if project:
                if not vals.get("source_location_id"):
                    vals["source_location_id"] = (
                        project.material_source_location_id.id or False)
                if not vals.get("destination_location_id"):
                    vals["destination_location_id"] = (
                        project.material_destination_location_id.id or False)
        return super().create(vals_list)

    @api.constrains("planned_quantity")
    def _check_planned_quantity(self):
        for line in self:
            if line.planned_quantity <= 0:
                raise ValidationError(_(
                    "Quantity must be greater than zero."
                ))

    @api.constrains("project_id", "task_id")
    def _check_task_project(self):
        for line in self:
            if line.task_id.project_id != line.project_id:
                raise ValidationError(_(
                    "The selected task does not belong to this project."
                ))

    @api.constrains("product_id")
    def _check_product_storable(self):
        for line in self:
            if line.product_id and not line.product_id.is_storable:
                raise ValidationError(_(
                    "Only storable products can be planned as project "
                    "material. '%(product)s' is not a storable product.",
                    product=line.product_id.display_name,
                ))

    def write(self, vals):
        # Approved lines are immutable — a changed need is a new draft line,
        # never an edit on an approved one (BRD §19/§20).
        locked = self.filtered(lambda line: line.state == "approved")
        if locked:
            raise UserError(_(
                "Approved material plan lines cannot be modified. "
                "Create a new draft line instead."
            ))
        return super().write(vals)

    def unlink(self):
        locked = self.filtered(lambda line: line.state == "approved")
        # material_plan_force_unlink: admin/test cleanup escape hatch —
        # never exposed in the UI; cancelled pickings should be removed
        # first so no stock reservation lingers.
        if locked and not self.env.context.get("material_plan_force_unlink"):
            raise UserError(_(
                "Approved material plan lines cannot be deleted — "
                "they are linked to stock transfers."
            ))
        return super().unlink()

    # ------------------------------------------------------------------
    # Approval: group by (project, source, destination) → one stock.picking
    # per group, one stock.move per line. Everything after creation
    # (confirm, reservation, shortage, replenishment) is standard Odoo.
    # ------------------------------------------------------------------
    def action_approve(self):
        drafts = self.filtered(lambda line: line.state == "draft")
        if not drafts:
            raise UserError(_("There are no draft lines to approve."))
        for line in drafts:
            if not line.source_location_id or not line.destination_location_id:
                raise UserError(_(
                    "Line %(name)s has no source/destination location.",
                    name=line.display_name,
                ))
        groups = defaultdict(lambda: self.env["project.material.plan"])
        for line in drafts:
            key = (line.project_id.id, line.source_location_id.id,
                   line.destination_location_id.id)
            groups[key] |= line
        for (project_id, source_id, dest_id), lines in groups.items():
            lines._create_picking(source_id, dest_id)
        drafts.state = "approved"
        return True

    def _create_picking(self, source_id, destination_id):
        """One standard internal transfer for this location pair."""
        source = self.env["stock.location"].browse(source_id)
        picking_type = self._get_internal_picking_type(source)
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": source_id,
            "location_dest_id": destination_id,
            "origin": _("Material Plan / %s") % self.project_id.name,
            "company_id": self.project_id.company_id.id or self.env.company.id,
            "scheduled_date": min(
                fields.Datetime.to_datetime(line.required_date)
                for line in self if line.required_date
            ),
        })
        self.env["stock.move"].create([
            {
                "name": line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": line.planned_quantity,
                "product_uom": line.uom_id.id,
                "location_id": source_id,
                "location_dest_id": destination_id,
                "date": fields.Datetime.to_datetime(line.required_date),
                "origin": picking.origin,
                "picking_id": picking.id,
                "company_id": picking.company_id.id,
                "material_plan_line_id": line.id,
            }
            for line in self
        ])
        # Hand off to standard Odoo: confirm the transfer, then let the
        # standard reservation engine run — no custom reservation logic.
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _get_internal_picking_type(self, source_location):
        """Pick the warehouse's internal transfer type that owns the source
        location; fall back to any internal type of the company."""
        PickingType = self.env["stock.picking.type"]
        company_id = self.project_id.company_id.id or self.env.company.id
        warehouse = self.env["stock.warehouse"].search([
            ("view_location_id", "parent_of", source_location.id),
            ("company_id", "=", company_id),
        ], limit=1)
        domain = [("code", "=", "internal")]
        if warehouse:
            domain.append(("warehouse_id", "=", warehouse.id))
        else:
            domain.append(("company_id", "=", company_id))
        picking_type = PickingType.search(domain, limit=1)
        if not picking_type:
            picking_type = PickingType.search([
                ("code", "=", "internal"), ("company_id", "=", company_id),
            ], limit=1)
        if not picking_type:
            raise UserError(_(
                "No internal transfer operation type found. "
                "Configure a warehouse with an internal picking type."
            ))
        return picking_type

    def action_open_form(self):
        """Editable lists don't navigate to the record form on row click —
        the per-row button opens the standard form for detail/traceability."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.material.plan",
            "res_id": self.id,
            "views": [[False, "form"]],
            "target": "current",
        }

    def action_open_transfers(self):
        pickings = self.picking_ids
        if len(pickings) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Transfer"),
                "res_model": "stock.picking",
                "res_id": pickings.id,
                "views": [[False, "form"]],
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Transfers"),
            "res_model": "stock.picking",
            "domain": [["id", "in", pickings.ids]],
            "view_mode": "list,form",
            "target": "current",
        }
