# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectMaterialPlan(models.Model):
    """Material planning lines for a project (BRD: Material Plan).

    Each line links a real ``product.product`` to a Task/WBS of the same
    project. This is deliberately separate from the human/equipment
    Resource Plan: products stay products so a later phase can turn a
    Material Plan into Material Requirement → Stock/Purchase/MRP flows
    (BoM explosion is NOT done here — that belongs to MRP execution).
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
    )
    description = fields.Char(string="Description")
    planned_quantity = fields.Float(
        string="Planned Quantity", required=True, default=1.0,
    )
    # Editable computed default: the product's own UoM is used, but the
    # planner may pick another UoM of the same category if needed.
    uom_id = fields.Many2one(
        "uom.uom", string="UoM", required=True,
        compute="_compute_uom_id", store=True, readonly=False,
    )
    required_date = fields.Date(
        string="Required Date",
        compute="_compute_required_date", store=True, readonly=False,
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
    # Cost scaffolding: the price always comes from the product record —
    # no duplicated pricing model. Useful today for review, required by a
    # future Material Requirement → Purchase flow.
    unit_cost = fields.Float(
        string="Unit Cost", related="product_id.standard_price", readonly=True,
    )
    planned_cost = fields.Monetary(
        string="Planned Cost", currency_field="currency_id",
        compute="_compute_planned_cost",
    )
    # Lets the standard search view group/filter by the WBS parent without
    # flattening the real hierarchy.
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
            line.uom_id = line.product_id.uom_id

    @api.depends("task_id.date_deadline")
    def _compute_required_date(self):
        for line in self:
            if not line.required_date:
                deadline = line.task_id.date_deadline
                line.required_date = deadline.date() if deadline else False

    @api.depends("planned_quantity", "product_id.standard_price")
    def _compute_planned_cost(self):
        for line in self:
            line.planned_cost = line.planned_quantity * (line.unit_cost or 0.0)

    @api.constrains("project_id", "task_id", "product_id")
    def _check_unique_task_product(self):
        """One material line per Project + Task + Product — adding the same
        product to the same task again must update the existing quantity."""
        for line in self:
            if not (line.project_id and line.task_id and line.product_id):
                continue
            duplicate = self.search_count([
                ("id", "!=", line.id),
                ("project_id", "=", line.project_id.id),
                ("task_id", "=", line.task_id.id),
                ("product_id", "=", line.product_id.id),
            ])
            if duplicate:
                raise ValidationError(_(
                    "A material line for %(task)s and %(product)s already "
                    "exists in this project. Update the quantity of the "
                    "existing line instead of adding a duplicate.",
                    task=line.task_id.display_name,
                    product=line.product_id.display_name,
                ))

    @api.constrains("planned_quantity")
    def _check_planned_quantity(self):
        for line in self:
            if line.planned_quantity <= 0:
                raise ValidationError(_(
                    "Planned quantity must be greater than zero."
                ))

    @api.constrains("project_id", "task_id")
    def _check_task_project(self):
        for line in self:
            if line.task_id.project_id != line.project_id:
                raise ValidationError(_(
                    "The selected task does not belong to this project."
                ))
