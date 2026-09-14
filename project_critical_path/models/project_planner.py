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

    def get_planner_data(self):
        """Return the project's tasks in WBS order for the Planner Workspace.

        The list is already flattened in display order so the WBS panel and the
        Gantt timeline share the exact same row sequence.
        """
        self.ensure_one()
        tasks = self.env["project.task"].with_context(active_test=False).search(
            [("project_id", "=", self.id)]
        )
        ordered = tasks.sorted(key=lambda task: (task.wbs_sort_key or "", task.sequence, task.id))
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
                }
                for task in ordered
            ],
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
            vals["date_assign"] = _local_day_to_utc(self, values["date_start"], 9)
        if "date_stop" in values:
            vals["date_deadline"] = _local_day_to_utc(self, values["date_stop"], 18)
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


def _local_day_to_utc(record, day_str, hour):
    """Convert a local ``YYYY-MM-DD`` day at ``hour`` to a naive UTC datetime."""
    if not day_str:
        return False
    local = datetime.strptime(day_str, "%Y-%m-%d").replace(hour=hour)
    tz = timezone(record.env.user.tz or "UTC")
    return tz.localize(local).astimezone(UTC).replace(tzinfo=None)
