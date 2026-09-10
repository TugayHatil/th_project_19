# -*- coding: utf-8 -*-

from odoo import fields, models


class ProjectCriticalPathChange(models.Model):
    """A task entering or leaving a baseline critical-path set."""

    _name = "project.critical.path.change"
    _description = "Project Critical Path Change"
    _order = "sequence, id"

    baseline_id = fields.Many2one(
        "project.critical.path.baseline", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    task_id = fields.Many2one("project.task", ondelete="set null", readonly=True)
    task_name = fields.Char(required=True, readonly=True)
    baseline_is_critical = fields.Boolean(readonly=True)
    current_is_critical = fields.Boolean(readonly=True)
    change_type = fields.Selection([
        ("added", "Entered Critical Path"),
        ("removed", "Left Critical Path"),
    ], required=True, readonly=True)
