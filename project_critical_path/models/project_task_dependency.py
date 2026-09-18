# -*- coding: utf-8 -*-

from odoo import api, fields, models

from .project_planner import _planner_hours_per_day


class ProjectTaskDependency(models.Model):
    """Per-edge attributes of a task dependency (BRD: Dependency Lag).

    The plain ``depend_on_ids`` many2many stays the structural source of
    truth — Odoo views, the gantt and the planner all write it directly.
    This model carries the scheduling attributes of each edge: the
    relationship type (FS/SS/FF/SF) and the lag. Rows are reconciled
    lazily by ``project.project._ensure_dependency_records`` so every
    write path is covered without fragile inverse-field hooks.
    """

    _name = "project.task.dependency"
    _description = "Task Dependency"
    _order = "id"

    task_id = fields.Many2one(
        "project.task", string="Task", required=True, ondelete="cascade", index=True,
    )
    depends_on_id = fields.Many2one(
        "project.task", string="Depends On", required=True, ondelete="cascade", index=True,
    )
    project_id = fields.Many2one(
        related="task_id.project_id", store=True, index=True,
    )
    relationship_type = fields.Selection(
        [
            ("fs", "Finish-to-Start (FS)"),
            ("ss", "Start-to-Start (SS)"),
            ("ff", "Finish-to-Finish (FF)"),
            ("sf", "Start-to-Finish (SF)"),
        ],
        string="Relationship Type", default="fs", required=True,
    )
    # Positive = waiting time after the predecessor point; negative = lead
    # (the successor may start earlier). 0 keeps the classic behaviour.
    lag = fields.Float(string="Lag", default=0.0)
    lag_unit = fields.Selection(
        [("hours", "Hours"), ("days", "Days")],
        string="Lag Unit", default="hours", required=True,
    )
    # Normalized to working hours — the unit the CPM schedule computes in.
    lag_hours = fields.Float(
        string="Lag (Hours)", compute="_compute_lag_hours", store=True,
    )

    _task_dependency_unique = models.Constraint(
        "UNIQUE(task_id, depends_on_id)",
        "A dependency between these two tasks already exists.",
    )

    @api.depends("lag", "lag_unit")
    def _compute_lag_hours(self):
        for dependency in self:
            factor = (
                _planner_hours_per_day(dependency)
                if dependency.lag_unit == "days"
                else 1.0
            )
            dependency.lag_hours = (dependency.lag or 0.0) * factor

    def _serialize(self):
        """Compact edge payload for the Planner Workspace."""
        self.ensure_one()
        return {
            "task_id": self.depends_on_id.id,
            "type": self.relationship_type or "fs",
            "lag": self.lag or 0.0,
            "unit": self.lag_unit or "hours",
            "lag_hours": self.lag_hours or 0.0,
        }
