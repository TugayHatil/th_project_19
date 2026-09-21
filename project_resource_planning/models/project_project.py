# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import _, api, fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    resource_requirement_ids = fields.One2many(
        "project.task.resource.requirement", "project_id", string="Resource Plan", readonly=True,
    )
    resource_plan_summary_ids = fields.One2many(
        "project.resource.plan.summary", "project_id", string="Resource Summary", readonly=True,
    )
    resource_assignment_ids = fields.One2many(
        "project.task.resource.assignment", "project_id", string="Resource Assignments", readonly=True,
    )
    # The project selects the rate templates it plans with — typically one
    # record per role (each template may carry a role + currency + rate).
    # Rates are snapshot onto each requirement on create, so later template
    # edits never reprice the existing plan (BRD §9/§10).
    resource_rate_template_ids = fields.Many2many(
        "project.resource.rate.template", string="Resource Rate Templates",
        domain=[("active", "=", True)],
    )
    resource_currency_id = fields.Many2one(
        "res.currency", string="Resource Currency", readonly=True, copy=False,
    )
    resource_cost_currency_id = fields.Many2one(
        "res.currency", compute="_compute_resource_cost_currency",
    )
    planned_resource_cost = fields.Monetary(
        string="Planned Resource Cost", compute="_compute_planned_resource_cost",
        currency_field="resource_cost_currency_id", readonly=True,
    )
    # Material Plan defaults (BRD §6): every new plan line starts with the
    # project's source/destination — both are editable per line.
    material_source_location_id = fields.Many2one(
        "stock.location", string="Material Source Location",
        domain="[('usage', '=', 'internal')]",
        help="Default source location for this project's material plan lines.",
    )
    material_destination_location_id = fields.Many2one(
        "stock.location", string="Material Destination Location",
        domain="[('usage', '=', 'internal')]",
        help="Default destination location for this project's material plan lines.",
    )
    # Transfers created by this project's material plan lines — resolved
    # through the stored stock.move link; no redundant relation on
    # stock.picking (BRD: UI navigation only).
    material_picking_ids = fields.Many2many(
        "stock.picking", string="Material Transfers",
        compute="_compute_material_pickings",
    )
    material_picking_count = fields.Integer(
        string="Material Transfer Count", compute="_compute_material_pickings",
    )

    @api.depends("resource_currency_id", "resource_rate_template_ids.currency_id")
    def _compute_resource_cost_currency(self):
        for project in self:
            project.resource_cost_currency_id = (
                project.resource_currency_id
                or project.resource_rate_template_ids[:1].currency_id
                or self.env.company.currency_id
            )

    def _sync_resource_rate_fields(self):
        """Copy the currency of the selected templates onto the project."""
        for project in self:
            currency = project.resource_rate_template_ids[:1].currency_id
            project.resource_currency_id = currency.id if currency else False

    @api.onchange("resource_rate_template_ids")
    def _onchange_resource_rate_template_ids(self):
        self._sync_resource_rate_fields()

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        for project, vals in zip(projects, vals_list):
            if vals.get("resource_rate_template_ids"):
                project._sync_resource_rate_fields()
        return projects

    def write(self, vals):
        result = super().write(vals)
        if "resource_rate_template_ids" in vals:
            self._sync_resource_rate_fields()
        return result

    @api.depends("resource_requirement_ids.planned_cost")
    def _compute_planned_resource_cost(self):
        for project in self:
            project.planned_resource_cost = sum(
                project.resource_requirement_ids.mapped("planned_cost")
            )

    def _get_baseline_resource_vals(self):
        """Real planned hours/cost frozen on the baseline — overrides the
        core hook that stores zeros when this addon is not installed."""
        self.ensure_one()
        return {
            "planned_resource_hours": sum(
                self.resource_requirement_ids.mapped("planned_hours")
            ),
            "planned_resource_cost": self.planned_resource_cost,
            "currency_id": self.resource_cost_currency_id.id or False,
        }

    def action_open_material_plan(self):
        """Material Plan (BRD): project-scoped standard list view — the
        single entry point for material planning, next to Planner and the
        Resource Board."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Material Plan"),
            "res_model": "project.material.plan",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id},
        }

    def _compute_material_pickings(self):
        Picking = self.env["stock.picking"]
        for project in self:
            pickings = Picking.search([
                ("move_ids.material_plan_line_id.project_id", "=", project.id),
            ])
            project.material_picking_ids = pickings
            project.material_picking_count = len(pickings)

    def action_open_material_transfers(self):
        """Project → Transfers (BRD §6/§10): the standard stock.picking
        list scoped to pickings created by THIS project's material plan
        lines — existing relations only, no custom transfer screen."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Transfers"),
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
            "domain": [("id", "in", self.material_picking_ids.ids)],
            "context": {"create": False},
        }

    def action_open_resource_roles(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Resource Roles"),
            "res_model": "project.resource.role",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
        }

    def _recalculate_resource_plan(self):
        Summary = self.env["project.resource.plan.summary"]
        Requirement = self.env["project.task.resource.requirement"]
        for project in self:
            requirements = Requirement.search([("project_id", "=", project.id)])
            totals = defaultdict(
                lambda: {"quantity": 0.0, "planned_hours": 0.0, "planned_cost": 0.0}
            )
            for requirement in requirements:
                totals[requirement.role_id.id]["quantity"] += requirement.quantity or 0.0
                totals[requirement.role_id.id]["planned_hours"] += requirement.planned_hours or 0.0
                totals[requirement.role_id.id]["planned_cost"] += requirement.planned_cost or 0.0
            Summary.search([("project_id", "=", project.id)]).unlink()
            Summary.create([
                {
                    "project_id": project.id,
                    "role_id": role_id,
                    "total_quantity": values["quantity"],
                    "total_planned_hours": values["planned_hours"],
                    "total_planned_cost": values["planned_cost"],
                }
                for role_id, values in totals.items()
            ])
