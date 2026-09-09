# -*- coding: utf-8 -*-

from odoo import fields, models


class ProjectCriticalPath(models.Model):
    """A saved result of one maximum-duration task chain in a project."""

    _name = "project.critical.path"
    _description = "Project Critical Path"
    _order = "sequence, id"

    project_id = fields.Many2one(
        "project.project", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(required=True, default=10)
    name = fields.Char(required=True, readonly=True)
    duration = fields.Float(string="Duration", required=True, readonly=True)
    task_ids = fields.Many2many(
        "project.task", "project_critical_path_task_rel",
        "critical_path_id", "task_id", string="Tasks", readonly=True,
    )
    task_path = fields.Char(string="Task Path", required=True, readonly=True)
