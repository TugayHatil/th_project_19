# -*- coding: utf-8 -*-

from datetime import datetime

from odoo import _, api, fields, models


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
                    "date_start": self._planner_serialize_date(task.date_assign),
                    "date_stop": self._planner_serialize_date(task.date_deadline),
                    "progress": task.progress or 0.0,
                }
                for task in ordered
            ],
        }

    def _planner_serialize_date(self, value):
        """Serialize a task date/datetime to a ``YYYY-MM-DD`` day in user tz."""
        if not value:
            return False
        if isinstance(value, datetime):
            value = fields.Datetime.context_timestamp(self, value)
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
