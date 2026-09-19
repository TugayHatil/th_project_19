# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = "project.task"

    critical_early_start = fields.Float(string="Early Start", readonly=True)
    critical_early_finish = fields.Float(string="Early Finish", readonly=True)
    critical_late_start = fields.Float(string="Late Start", readonly=True)
    critical_late_finish = fields.Float(string="Late Finish", readonly=True)
    critical_slack = fields.Float(string="Slack", readonly=True)
    is_critical = fields.Boolean(string="Critical Task", readonly=True)
    delay_baseline_duration = fields.Float(string="Baseline Duration", readonly=True)
    delay_duration_variance = fields.Float(string="Duration Variance", readonly=True)
    delay_project_impact = fields.Float(string="Project Impact", readonly=True)
    delay_impact_status = fields.Selection([
        ("critical_impact", "Critical Impact"),
        ("within_slack", "Within Slack"),
        ("duration_reduced", "Duration Reduced"),
        ("no_impact", "No Impact"),
    ], string="Impact Status", readonly=True)
    delay_impact_chain = fields.Text(string="Impact Chain", readonly=True)
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

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks.mapped("project_id")._recalculate_critical_paths()
        tasks.mapped("parent_id")._sync_parent_window()
        return tasks

    def write(self, vals):
        affected_projects = self.mapped("project_id")
        old_parents = self.mapped("parent_id") if "parent_id" in vals else self.env["project.task"]
        result = super().write(vals)
        if {"project_id", "parent_id", "allocated_hours", "depend_on_ids", "dependent_ids"}.intersection(vals):
            (affected_projects | self.mapped("project_id"))._recalculate_critical_paths()
        # BRD auto-shift: a date change can violate successor dependency
        # bounds — the cascade runs once per project and suppresses its
        # own re-trigger via context.
        if {"date_assign", "date_deadline"}.intersection(vals) and not self.env.context.get(
            "cp_skip_auto_schedule"
        ):
            for project in self.mapped("project_id"):
                project._schedule_dependents(
                    self.filtered(lambda task: task.project_id == project)
                )
        # Parent window rollup: a parent's date range mirrors the min/max of
        # its dated children. The parent write re-enters this hook, so the
        # rollup bubbles all the way to the root.
        if {"date_assign", "date_deadline", "parent_id"}.intersection(vals):
            (self.mapped("parent_id") | old_parents)._sync_parent_window()
        return result

    def _sync_parent_window(self):
        """``self`` = parent tasks — recompute each one's date window as the
        min/max over its dated children, so parent bars stay consistent with
        the WBS children after moves, resizes and cascade shifts."""
        for parent in self:
            children = parent.child_ids.filtered(
                lambda child: child.date_assign and child.date_deadline
            )
            if not children:
                continue
            start = min(children.mapped("date_assign"))
            stop = max(children.mapped("date_deadline"))
            vals = {}
            if parent.date_assign != start:
                vals["date_assign"] = start
            if parent.date_deadline != stop:
                vals["date_deadline"] = stop
            if vals:
                parent.write(vals)

    def unlink(self):
        affected_projects = self.mapped("project_id")
        result = super().unlink()
        affected_projects._recalculate_critical_paths()
        return result
