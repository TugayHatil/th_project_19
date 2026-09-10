# -*- coding: utf-8 -*-

from odoo import fields, models


class ProjectTaskDelayImpact(models.Model):
    """Current delay-impact analysis rows, rebuilt from the latest baseline."""

    _name = "project.task.delay.impact"
    _description = "Project Task Delay Impact"
    _order = "project_impact desc, id"

    project_id = fields.Many2one("project.project", required=True, ondelete="cascade", index=True)
    baseline_id = fields.Many2one(
        "project.critical.path.baseline", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    task_id = fields.Many2one("project.task", required=True, ondelete="cascade")
    baseline_duration = fields.Float(readonly=True)
    current_duration = fields.Float(readonly=True)
    duration_variance = fields.Float(readonly=True)
    project_impact = fields.Float(readonly=True)
    impact_status = fields.Selection([
        ("critical_impact", "Critical Impact"),
        ("within_slack", "Within Slack"),
        ("duration_reduced", "Duration Reduced"),
        ("no_impact", "No Impact"),
    ], readonly=True)
    impact_chain = fields.Text(readonly=True)
