# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = "project.task"

    resource_requirement_ids = fields.One2many(
        "project.task.resource.requirement", "task_id", string="Resource Requirements",
    )
    resource_cost_currency_id = fields.Many2one(
        related="project_id.resource_cost_currency_id",
    )
    planned_resource_cost = fields.Monetary(
        string="Planned Resource Cost", compute="_compute_planned_resource_cost",
        currency_field="resource_cost_currency_id", readonly=True,
    )

    @api.depends("resource_requirement_ids.planned_cost")
    def _compute_planned_resource_cost(self):
        for task in self:
            task.planned_resource_cost = sum(
                task.resource_requirement_ids.mapped("planned_cost")
            )

    def _planner_resource_fields(self):
        """Role names/categories for the planner payload — overrides the
        core hook that ships empty lists when this addon is absent."""
        self.ensure_one()
        return {
            "role_names": sorted(set(
                self.resource_requirement_ids.mapped("role_id.name")
            )),
            # Requirement categories — needed (not only assigned) resource
            # types, so the Resource Type group-by sees open requirements too.
            "role_categories": sorted(set(
                self.resource_requirement_ids.mapped("role_id.category")
            )),
        }
