# -*- coding: utf-8 -*-

from odoo import models


class ProjectCriticalPathBaseline(models.Model):
    _inherit = "project.critical.path.baseline"

    def _get_task_resource_snapshot(self, task):
        """Real requirement totals frozen on the baseline line — overrides
        the core hook that writes zeros when this addon is absent."""
        self.ensure_one()
        return {
            "planned_hours": sum(task.resource_requirement_ids.mapped("planned_hours")),
            "planned_cost": sum(task.resource_requirement_ids.mapped("planned_cost")),
            "currency_id": (
                task.resource_requirement_ids[:1].currency_id
                or self.project_id.resource_cost_currency_id
            ).id or False,
        }
