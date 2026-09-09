# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProjectCriticalPathBaseline(models.Model):
    """An immutable, user-created snapshot of a project's calculated plan."""

    _name = "project.critical.path.baseline"
    _description = "Project Critical Path Baseline"
    _order = "revision_number desc, id desc"
    _rec_name = "name"

    project_id = fields.Many2one("project.project", required=True, ondelete="cascade", index=True)
    name = fields.Char(required=True, readonly=True, copy=False)
    revision_number = fields.Integer(required=True, readonly=True, copy=False)
    created_on = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, copy=False)
    created_by_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, required=True, readonly=True, copy=False,
    )
    project_duration = fields.Float(required=True, readonly=True, copy=False)
    critical_path_duration = fields.Float(required=True, readonly=True, copy=False)
    critical_path_signature = fields.Text(readonly=True, copy=False)
    line_ids = fields.One2many(
        "project.critical.path.baseline.line", "baseline_id", string="Task Snapshots", readonly=True,
    )
    current_project_duration = fields.Float(compute="_compute_current_comparison")
    current_critical_path_duration = fields.Float(compute="_compute_current_comparison")
    project_duration_delta = fields.Float(compute="_compute_current_comparison")
    critical_path_duration_delta = fields.Float(compute="_compute_current_comparison")
    current_critical_path_signature = fields.Text(compute="_compute_current_comparison")
    critical_path_changed = fields.Boolean(compute="_compute_current_comparison")

    @api.depends("project_id.critical_path_duration", "project_id.critical_path_ids.task_path")
    def _compute_current_comparison(self):
        for baseline in self:
            project = baseline.project_id
            current_signature = project._get_critical_path_signature() if project else False
            baseline.current_project_duration = project.critical_path_duration if project else 0.0
            baseline.current_critical_path_duration = project.critical_path_duration if project else 0.0
            baseline.project_duration_delta = baseline.current_project_duration - baseline.project_duration
            baseline.critical_path_duration_delta = (
                baseline.current_critical_path_duration - baseline.critical_path_duration
            )
            baseline.current_critical_path_signature = current_signature
            baseline.critical_path_changed = current_signature != (baseline.critical_path_signature or False)

    def _create_snapshot_lines(self):
        for baseline in self:
            tasks = self.env["project.task"].with_context(active_test=False).search(
                [("project_id", "=", baseline.project_id.id)], order="id",
            )
            self.env["project.critical.path.baseline.line"].create([
                {
                    "baseline_id": baseline.id,
                    "task_id": task.id,
                    "task_name": task.display_name,
                    "parent_task_name": task.parent_id.display_name if task.parent_id else False,
                    "allocated_hours": task.allocated_hours,
                    # Odoo Project exposes its scheduled dates as date_assign and
                    # date_deadline.  Check the model fields for compatibility
                    # with installations that do not provide a planned_date_* API.
                    "planned_date_begin": task.date_assign if "date_assign" in task._fields else False,
                    "planned_date_end": task.date_deadline if "date_deadline" in task._fields else False,
                    "dependency_task_names": ", ".join(task.depend_on_ids.mapped("display_name")),
                    "early_start": task.critical_early_start,
                    "early_finish": task.critical_early_finish,
                    "late_start": task.critical_late_start,
                    "late_finish": task.critical_late_finish,
                    "slack": task.critical_slack,
                    "is_critical": task.is_critical,
                }
                for task in tasks
            ])

    def write(self, vals):
        protected = {
            "project_id", "name", "revision_number", "created_on", "created_by_id",
            "project_duration", "critical_path_duration", "critical_path_signature", "line_ids",
        }
        if protected.intersection(vals):
            raise UserError(_("Baseline snapshots cannot be modified."))
        return super().write(vals)

    def unlink(self):
        raise UserError(_("Baseline snapshots cannot be deleted."))


class ProjectCriticalPathBaselineLine(models.Model):
    """Immutable task-level values belonging to one plan baseline."""

    _name = "project.critical.path.baseline.line"
    _description = "Project Critical Path Baseline Task"
    _order = "id"

    baseline_id = fields.Many2one(
        "project.critical.path.baseline", required=True, ondelete="cascade", index=True,
    )
    task_id = fields.Many2one("project.task", ondelete="set null", readonly=True)
    task_name = fields.Char(required=True, readonly=True)
    parent_task_name = fields.Char(readonly=True)
    allocated_hours = fields.Float(readonly=True)
    planned_date_begin = fields.Datetime(readonly=True)
    planned_date_end = fields.Datetime(readonly=True)
    dependency_task_names = fields.Text(readonly=True)
    early_start = fields.Float(readonly=True)
    early_finish = fields.Float(readonly=True)
    late_start = fields.Float(readonly=True)
    late_finish = fields.Float(readonly=True)
    slack = fields.Float(readonly=True)
    is_critical = fields.Boolean(readonly=True)
    current_allocated_hours = fields.Float(compute="_compute_current_values")
    allocated_hours_delta = fields.Float(compute="_compute_current_values")
    current_early_start = fields.Float(compute="_compute_current_values")
    current_early_finish = fields.Float(compute="_compute_current_values")
    current_late_start = fields.Float(compute="_compute_current_values")
    current_late_finish = fields.Float(compute="_compute_current_values")
    current_slack = fields.Float(compute="_compute_current_values")
    current_is_critical = fields.Boolean(compute="_compute_current_values")

    @api.depends(
        "task_id.allocated_hours", "task_id.critical_early_start", "task_id.critical_early_finish",
        "task_id.critical_late_start", "task_id.critical_late_finish", "task_id.critical_slack",
        "task_id.is_critical",
    )
    def _compute_current_values(self):
        for line in self:
            task = line.task_id
            line.current_allocated_hours = task.allocated_hours if task else 0.0
            line.allocated_hours_delta = line.current_allocated_hours - line.allocated_hours
            line.current_early_start = task.critical_early_start if task else 0.0
            line.current_early_finish = task.critical_early_finish if task else 0.0
            line.current_late_start = task.critical_late_start if task else 0.0
            line.current_late_finish = task.critical_late_finish if task else 0.0
            line.current_slack = task.critical_slack if task else 0.0
            line.current_is_critical = task.is_critical if task else False

    def write(self, vals):
        raise UserError(_("Baseline task snapshots cannot be modified."))

    def unlink(self):
        raise UserError(_("Baseline task snapshots cannot be deleted."))
