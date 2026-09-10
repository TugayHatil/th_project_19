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

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks.mapped("project_id")._recalculate_critical_paths()
        return tasks

    def write(self, vals):
        affected_projects = self.mapped("project_id")
        result = super().write(vals)
        if {"project_id", "allocated_hours", "depend_on_ids", "dependent_ids"}.intersection(vals):
            (affected_projects | self.mapped("project_id"))._recalculate_critical_paths()
        return result

    def unlink(self):
        affected_projects = self.mapped("project_id")
        result = super().unlink()
        affected_projects._recalculate_critical_paths()
        return result
