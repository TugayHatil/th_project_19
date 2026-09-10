# -*- coding: utf-8 -*-

import json

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
    critical_path_snapshot = fields.Text(readonly=True, copy=False)
    line_ids = fields.One2many(
        "project.critical.path.baseline.line", "baseline_id", string="Task Snapshots", readonly=True,
    )
    critical_path_change_line_ids = fields.One2many(
        "project.critical.path.change", "baseline_id", string="Critical Path Changes", readonly=True,
    )
    critical_path_change_summary = fields.Text(readonly=True, copy=False)
    previous_baseline_id = fields.Many2one(
        "project.critical.path.baseline", string="Previous Baseline", readonly=True, copy=False,
    )
    history_project_duration_variance = fields.Float(
        string="Project Duration Variance", readonly=True, copy=False,
    )
    history_critical_path_duration_variance = fields.Float(
        string="Critical Path Duration Variance", readonly=True, copy=False,
    )
    history_critical_path_changed = fields.Selection([
        ("yes", "Yes"),
        ("no", "No"),
    ], string="Previous Baseline CP Changed", readonly=True, copy=False)
    history_added_task_names = fields.Text(string="Entered Critical Path", readonly=True, copy=False)
    history_removed_task_names = fields.Text(string="Left Critical Path", readonly=True, copy=False)
    history_change_summary = fields.Text(string="Previous Baseline Change Summary", readonly=True, copy=False)
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

    def _recalculate_critical_path_changes(self):
        """Compare saved critical-path membership with the current saved paths."""
        Change = self.env["project.critical.path.change"]
        for baseline in self:
            project = baseline.project_id
            current_paths = project.critical_path_ids
            current_task_ids = set(current_paths.mapped("task_ids").ids)
            current_by_id = {task.id: task for task in current_paths.mapped("task_ids")}
            try:
                baseline_paths = json.loads(baseline.critical_path_snapshot or "[]")
            except (TypeError, ValueError):
                baseline_paths = []
            baseline_task_ids = {
                task_id for path in baseline_paths for task_id in path.get("task_ids", [])
            }
            # Baselines made before BRD-07 only have the task snapshots.  This
            # fallback preserves useful analysis for them until a new baseline is made.
            if not baseline_task_ids:
                baseline_task_ids = set(baseline.line_ids.filtered("is_critical").mapped("task_id").ids)
            baseline_names = {
                line.task_id.id: line.task_name for line in baseline.line_ids if line.task_id
            }
            added_ids = current_task_ids - baseline_task_ids
            removed_ids = baseline_task_ids - current_task_ids
            Change.search([("baseline_id", "=", baseline.id)]).unlink()
            change_values = []
            for task_id in sorted(added_ids):
                task = current_by_id[task_id]
                change_values.append({
                    "baseline_id": baseline.id,
                    "sequence": 10,
                    "task_id": task.id,
                    "task_name": task.display_name,
                    "baseline_is_critical": False,
                    "current_is_critical": task.is_critical,
                    "change_type": "added",
                })
            for task_id in sorted(removed_ids):
                task = self.env["project.task"].browse(task_id).exists()
                change_values.append({
                    "baseline_id": baseline.id,
                    "sequence": 20,
                    "task_id": task.id if task else False,
                    "task_name": task.display_name if task else baseline_names.get(task_id, str(task_id)),
                    "baseline_is_critical": True,
                    "current_is_critical": task.is_critical if task else False,
                    "change_type": "removed",
                })
            if change_values:
                Change.create(change_values)
            if not change_values:
                summary = False
            else:
                added_names = [current_by_id[task_id].display_name for task_id in sorted(added_ids)]
                removed_names = [
                    (self.env["project.task"].browse(task_id).exists().display_name
                     if self.env["project.task"].browse(task_id).exists()
                     else baseline_names.get(task_id, str(task_id)))
                    for task_id in sorted(removed_ids)
                ]
                messages = [_("Critical Path changed.")]
                if added_names:
                    messages.append(_("Entered Critical Path: %s") % ", ".join(added_names))
                if removed_names:
                    messages.append(_("Left Critical Path: %s") % ", ".join(removed_names))
                messages.append(_("Duration: %(old).2f h → %(new).2f h (%(delta)+.2f h)") % {
                    "old": baseline.critical_path_duration,
                    "new": project.critical_path_duration,
                    "delta": project.critical_path_duration - baseline.critical_path_duration,
                })
                summary = "\n".join(messages)
            baseline.write({"critical_path_change_summary": summary})

    def _get_critical_path_snapshot_info(self):
        """Return task membership and names using frozen baseline values only."""
        self.ensure_one()
        try:
            paths = json.loads(self.critical_path_snapshot or "[]")
        except (TypeError, ValueError):
            paths = []
        task_ids, task_names = set(), {}
        for path in paths:
            task_ids.update(path.get("task_ids", []))
            for task in path.get("tasks", []):
                task_ids.add(task["id"])
                task_names[task["id"]] = task["name"]
        for line in self.line_ids.filtered("is_critical"):
            if line.task_id:
                task_ids.add(line.task_id.id)
                task_names.setdefault(line.task_id.id, line.task_name)
        return task_ids, task_names

    def _recalculate_history_comparisons(self):
        """Build each baseline's immutable-history summary against its predecessor."""
        for project in self.mapped("project_id"):
            baselines = self.search(
                [("project_id", "=", project.id)], order="revision_number, id",
            )
            previous = self.browse()
            for baseline in baselines:
                values = {
                    "previous_baseline_id": previous.id or False,
                    "history_project_duration_variance": 0.0,
                    "history_critical_path_duration_variance": 0.0,
                    "history_critical_path_changed": False,
                    "history_added_task_names": False,
                    "history_removed_task_names": False,
                    "history_change_summary": False,
                }
                if previous:
                    previous_ids, previous_names = previous._get_critical_path_snapshot_info()
                    current_ids, current_names = baseline._get_critical_path_snapshot_info()
                    added_ids = current_ids - previous_ids
                    removed_ids = previous_ids - current_ids
                    paths_changed = baseline.critical_path_signature != previous.critical_path_signature
                    values.update({
                        "history_project_duration_variance": (
                            baseline.project_duration - previous.project_duration
                        ),
                        "history_critical_path_duration_variance": (
                            baseline.critical_path_duration - previous.critical_path_duration
                        ),
                        "history_critical_path_changed": "yes" if paths_changed else "no",
                        "history_added_task_names": ", ".join(
                            current_names.get(task_id, str(task_id)) for task_id in sorted(added_ids)
                        ) or False,
                        "history_removed_task_names": ", ".join(
                            previous_names.get(task_id, str(task_id)) for task_id in sorted(removed_ids)
                        ) or False,
                    })
                    summary = [
                        _("Compared with %s.") % previous.name,
                        _("Project duration: %(old).2f h → %(new).2f h (%(delta)+.2f h)") % {
                            "old": previous.project_duration,
                            "new": baseline.project_duration,
                            "delta": values["history_project_duration_variance"],
                        },
                    ]
                    if paths_changed:
                        summary.append(_("Critical Path changed."))
                    if values["history_added_task_names"]:
                        summary.append(_("Entered: %s") % values["history_added_task_names"])
                    if values["history_removed_task_names"]:
                        summary.append(_("Left: %s") % values["history_removed_task_names"])
                    values["history_change_summary"] = "\n".join(summary)
                baseline.write(values)
                previous = baseline

    def write(self, vals):
        protected = {
            "project_id", "name", "revision_number", "created_on", "created_by_id",
            "project_duration", "critical_path_duration", "critical_path_signature",
            "critical_path_snapshot", "line_ids", "critical_path_change_line_ids",
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
