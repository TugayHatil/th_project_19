# -*- coding: utf-8 -*-

from datetime import datetime

from pytz import UTC, timezone

from odoo import Command, _, api, fields, models


def _serialize_planner_day(record, value):
    """Serialize a date/datetime field to a ``YYYY-MM-DD`` day in user tz."""
    if not value:
        return False
    if isinstance(value, datetime):
        return fields.Datetime.context_timestamp(record, value).date().isoformat()
    return value.isoformat()


class ProjectProjectPlanner(models.Model):
    _inherit = "project.project"

    def action_open_planner_workspace(self):
        """Open the Planner Workspace client action for this project."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "project_critical_path.planner_workspace",
            "name": _("Planner"),
            "params": {"project_id": self.id},
        }

    @api.model
    def get_planner_projects(self):
        """Return the projects selectable in the Planner Workspace picker."""
        return [
            {"id": project.id, "name": project.display_name}
            for project in self.search([], order="name")
        ]

    def get_planner_data(self, baseline_id=None):
        """Return the project's tasks in WBS order for the Planner Workspace.

        The list is already flattened in display order so the WBS panel and the
        Gantt timeline share the exact same row sequence.

        ``baseline_id`` optionally overrides the comparison baseline used for
        the ghost/variance layer so the Gantt can show a historical baseline
        against the current plan without touching any baseline record.
        """
        self.ensure_one()
        tasks = self.env["project.task"].with_context(active_test=False).search(
            [("project_id", "=", self.id)]
        )
        ordered = tasks.sorted(key=lambda task: (task.wbs_sort_key or "", task.sequence, task.id))
        baseline = self.delay_impact_baseline_id
        if baseline_id:
            override = self.env["project.critical.path.baseline"].browse(baseline_id).exists()
            if override and override.project_id == self:
                baseline = override
        baseline_by_task = {
            line.task_id.id: line for line in baseline.line_ids if line.task_id
        } if baseline else {}
        return {
            "project": {"id": self.id, "name": self.display_name},
            "tasks": [
                {
                    "id": task.id,
                    "name": task.name or "",
                    "wbs_code": task.wbs_code or "",
                    "wbs_level": task.wbs_level or 1,
                    "parent_id": task.parent_id.id or False,
                    "has_children": bool(task.child_ids),
                    "date_start": _serialize_planner_day(self, task.date_assign),
                    "date_stop": _serialize_planner_day(self, task.date_deadline),
                    "progress": task.progress or 0.0,
                    "is_critical": bool(task.is_critical),
                    "depend_on_ids": task.depend_on_ids.ids,
                    "baseline_name": baseline.name if baseline_by_task.get(task.id) else False,
                    "baseline_start": (
                        _serialize_planner_day(self, baseline_by_task[task.id].planned_date_begin)
                        if baseline_by_task.get(task.id) else False
                    ),
                    "baseline_stop": (
                        _serialize_planner_day(self, baseline_by_task[task.id].planned_date_end)
                        if baseline_by_task.get(task.id) else False
                    ),
                }
                for task in ordered
            ],
        }

    def get_planner_baseline_history(self):
        """Read-only list of this project's baseline versions, newest first.

        Only stored snapshot/history fields are serialized — nothing is
        recalculated, so opening the list stays cheap.
        """
        self.ensure_one()
        baselines = self.env["project.critical.path.baseline"].search(
            [("project_id", "=", self.id)]
        )
        return [
            {
                "id": baseline.id,
                "name": baseline.name,
                "created_on": fields.Datetime.to_string(baseline.created_on),
                "project_duration": baseline.project_duration or 0.0,
                "previous_id": baseline.previous_baseline_id.id or False,
                "previous_name": baseline.previous_baseline_id.name or False,
                "duration_variance": baseline.history_project_duration_variance or 0.0,
                "is_initial": not baseline.previous_baseline_id,
            }
            for baseline in baselines
        ]

    def get_planner_baseline_summary(self, baseline_id):
        """Read-only change summary of one baseline vs its previous version.

        Task-level changes are derived by comparing the frozen snapshot lines
        of the two consecutive baselines — no baseline or critical-path data
        is recomputed or modified.
        """
        self.ensure_one()
        baseline = self.env["project.critical.path.baseline"].browse(baseline_id).exists()
        if not baseline or baseline.project_id != self:
            return False
        previous = baseline.previous_baseline_id
        current_lines = {line.task_id.id: line for line in baseline.line_ids if line.task_id}
        previous_lines = {
            line.task_id.id: line for line in previous.line_ids if line.task_id
        } if previous else {}
        changes = []
        cp_changes = 0
        for task_id, line in current_lines.items():
            if not previous:
                break  # initial baseline has nothing to compare against
            prev = previous_lines.get(task_id)
            delta = round(
                line.allocated_hours - (prev.allocated_hours if prev else 0.0), 2,
            )
            entered = bool(line.is_critical) and not (prev and prev.is_critical)
            left = bool(prev and prev.is_critical) and not line.is_critical
            dates_changed = bool(prev) and (
                line.planned_date_begin != prev.planned_date_begin
                or line.planned_date_end != prev.planned_date_end
            )
            if not (delta or entered or left or dates_changed):
                continue
            changes.append({
                "task_id": task_id,
                "task_name": line.task_name,
                "delta_hours": delta,
                "old_hours": prev.allocated_hours if prev else False,
                "new_hours": line.allocated_hours,
                "entered_cp": entered,
                "left_cp": left,
                "new_task": prev is None,
                "removed_task": False,
                "dates_changed": dates_changed,
            })
            cp_changes += int(entered) + int(left)
        if previous:
            for task_id in sorted(set(previous_lines) - set(current_lines)):
                line = previous_lines[task_id]
                changes.append({
                    "task_id": task_id,
                    "task_name": line.task_name,
                    "delta_hours": False,
                    "old_hours": line.allocated_hours,
                    "new_hours": False,
                    "entered_cp": False,
                    "left_cp": False,
                    "new_task": False,
                    "removed_task": True,
                    "dates_changed": False,
                })
        changes.sort(key=lambda item: (-abs(item["delta_hours"] or 0.0), item["task_name"]))
        return {
            "id": baseline.id,
            "name": baseline.name,
            "created_on": fields.Datetime.to_string(baseline.created_on),
            "project_duration": baseline.project_duration or 0.0,
            "critical_path_duration": baseline.critical_path_duration or 0.0,
            "previous_id": previous.id or False,
            "previous_name": previous.name or False,
            "previous_duration": previous.project_duration if previous else False,
            "duration_variance": baseline.history_project_duration_variance or 0.0,
            "cp_duration_variance": baseline.history_critical_path_duration_variance or 0.0,
            "is_initial": not previous,
            "task_count": len(baseline.line_ids),
            "tasks_changed": len(changes),
            "cp_changes": cp_changes,
            "changes": changes,
        }


class ProjectTaskPlanner(models.Model):
    _inherit = "project.task"

    def get_planner_detail(self):
        """Return the task fields and dropdown options for the Quick Inspector."""
        self.ensure_one()
        project = self.project_id
        if project and "type_ids" in project._fields:
            stages = project.type_ids
        elif project:
            stages = self.env["project.task.type"].search([("project_ids", "in", project.id)])
        else:
            stages = self.env["project.task.type"].search([])
        users = self.env["res.users"].search([("share", "=", False)], order="name")
        baseline = project.delay_impact_baseline_id if project else self.env["project.critical.path.baseline"]
        line = baseline.line_ids.filtered(lambda item: item.task_id == self)[:1] if baseline else False
        baseline_start = _serialize_planner_day(line, line.planned_date_begin) if line else False
        baseline_stop = _serialize_planner_day(line, line.planned_date_end) if line else False
        return {
            "task": {
                "id": self.id,
                "name": self.name or "",
                "wbs_code": self.wbs_code or "",
                "is_critical": bool(self.is_critical),
                "critical_slack": self.critical_slack or 0.0,
                "date_start": _serialize_planner_day(self, self.date_assign),
                "date_stop": _serialize_planner_day(self, self.date_deadline),
                "allocated_hours": self.allocated_hours or 0.0,
                "effective_hours": getattr(self, "effective_hours", 0.0) or 0.0,
                # progress is stored as a 0..1 ratio; the inspector shows 0..100
                "progress": round((self.progress or 0.0) * 100, 1),
                "stage_id": self.stage_id.id or False,
                "user_ids": self.user_ids.ids,
                "depend_on_ids": self.depend_on_ids.ids,
                "dependent_ids": self.dependent_ids.ids,
            },
            "baseline": {
                "name": baseline.name if baseline else False,
                "has_line": bool(line),
                "date_start": baseline_start,
                "date_stop": baseline_stop,
                # day-based duration, same convention as the inspector duration
                "duration_days": (
                    (datetime.strptime(baseline_stop, "%Y-%m-%d")
                     - datetime.strptime(baseline_start, "%Y-%m-%d")).days
                    if baseline_start and baseline_stop else False
                ),
                "allocated_hours": line.allocated_hours if line else False,
                "is_critical": line.is_critical if line else None,
            },
            "impact": {
                "delay_baseline_duration": self.delay_baseline_duration or 0.0,
                "delay_duration_variance": self.delay_duration_variance or 0.0,
                "delay_project_impact": self.delay_project_impact or 0.0,
                "delay_impact_status": self.delay_impact_status or False,
                "delay_impact_chain": self.delay_impact_chain or False,
            },
            "options": {
                "stages": [{"id": stage.id, "name": stage.name} for stage in stages],
                "users": [{"id": user.id, "name": user.name} for user in users],
            },
        }

    def update_planner_task(self, values):
        """Write Quick Inspector edits to the task.

        ``date_start``/``date_stop`` are local ``YYYY-MM-DD`` days; they are
        stored at 09:00 / 18:00 in the user's timezone so the saved day never
        shifts across timezones.
        """
        self.ensure_one()
        vals = {}
        if "name" in values:
            vals["name"] = values["name"]
        if "date_start" in values:
            vals["date_assign"] = _local_day_to_utc(self, values["date_start"], self.date_assign, 9)
        if "date_stop" in values:
            vals["date_deadline"] = _local_day_to_utc(self, values["date_stop"], self.date_deadline, 18)
        # Keep allocated_hours (the duration used by critical-path, delay-impact
        # and baseline comparisons) in sync when the inspector duration changes.
        days = values.get("duration_days")
        if values.get("date_start") and values.get("date_stop") and days not in (None, False):
            stored_start = _serialize_planner_day(self, self.date_assign)
            stored_stop = _serialize_planner_day(self, self.date_deadline)
            stored_days = (
                (datetime.strptime(stored_stop, "%Y-%m-%d")
                 - datetime.strptime(stored_start, "%Y-%m-%d")).days
                if stored_start and stored_stop else None
            )
            if float(days) != stored_days:
                vals["allocated_hours"] = max(float(days), 0.0) * _planner_hours_per_day(self)
        if "progress" in values:
            vals["progress"] = min(max(values["progress"] or 0.0, 0.0), 100.0) / 100.0
        if "stage_id" in values:
            vals["stage_id"] = values["stage_id"] or False
        if "user_ids" in values:
            vals["user_ids"] = [Command.set(values["user_ids"] or [])]
        if "depend_on_ids" in values:
            vals["depend_on_ids"] = [Command.set(values["depend_on_ids"] or [])]
        if "dependent_ids" in values:
            vals["dependent_ids"] = [Command.set(values["dependent_ids"] or [])]
        self.write(vals)
        return True


def _local_day_to_utc(record, day_str, existing_dt, fallback_hour):
    """Convert a local ``YYYY-MM-DD`` day to naive UTC, keeping the stored
    time-of-day when the task already had a date (so drags do not reset
    hours) and falling back to ``fallback_hour`` otherwise."""
    if not day_str:
        return False
    hour, minute = fallback_hour, 0
    if existing_dt:
        local_existing = fields.Datetime.context_timestamp(record, existing_dt)
        hour, minute = local_existing.hour, local_existing.minute
    local = datetime.strptime(day_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
    tz = timezone(record.env.user.tz or "UTC")
    return tz.localize(local).astimezone(UTC).replace(tzinfo=None)


def _planner_hours_per_day(record):
    """Working hours per calendar day used to sync duration with planned hours."""
    project = record.project_id if "project_id" in record._fields else False
    calendar = False
    if project and "resource_calendar_id" in project._fields:
        calendar = project.resource_calendar_id
    if not calendar:
        calendar = record.env.company.resource_calendar_id
    return (calendar.hours_per_day if calendar else 0.0) or 8.0
