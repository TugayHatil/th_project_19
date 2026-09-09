# -*- coding: utf-8 -*-

from collections import deque

from odoo import _, fields, models
from odoo.exceptions import UserError


class ProjectProject(models.Model):
    _inherit = "project.project"

    critical_path_count = fields.Integer(string="Critical Path Count", readonly=True)
    critical_path_duration = fields.Float(string="Critical Path Duration", readonly=True)
    critical_path_ids = fields.One2many(
        "project.critical.path", "project_id", string="Critical Paths", readonly=True,
    )

    def action_calculate_critical_paths(self):
        self._recalculate_critical_paths()
        return True

    def _recalculate_critical_paths(self):
        """Rebuild saved critical paths using only this project's task graph.

        A task's ``allocated_hours`` is the Odoo 19 planned/allocated duration.
        The algorithm is a longest-path dynamic programme over the dependency DAG.
        All ties are retained, so multiple critical paths are saved.
        """
        Path = self.env["project.critical.path"].sudo()
        Task = self.env["project.task"].with_context(active_test=False)

        for project in self:
            tasks = Task.search([("project_id", "=", project.id)], order="id")
            task_by_id = {task.id: task for task in tasks}
            task_ids = set(task_by_id)

            predecessors = {
                task.id: {dependency.id for dependency in task.depend_on_ids if dependency.id in task_ids}
                for task in tasks
            }
            successors = {task.id: set() for task in tasks}
            for task_id, dependency_ids in predecessors.items():
                for dependency_id in dependency_ids:
                    successors[dependency_id].add(task_id)

            # Kahn topological sort; standard Odoo prevents cycles, but avoid
            # silently publishing an invalid result if legacy data contains one.
            in_degree = {task_id: len(ids) for task_id, ids in predecessors.items()}
            queue = deque(sorted(task_id for task_id, degree in in_degree.items() if not degree))
            ordered_ids = []
            while queue:
                task_id = queue.popleft()
                ordered_ids.append(task_id)
                for successor_id in sorted(successors[task_id]):
                    in_degree[successor_id] -= 1
                    if not in_degree[successor_id]:
                        queue.append(successor_id)

            if len(ordered_ids) != len(tasks):
                raise UserError(_("Critical paths cannot be calculated because task dependencies contain a cycle."))

            # duration_by_task is the longest duration ending at each task;
            # best_predecessors retains every predecessor that yields that value.
            duration_by_task = {}
            best_predecessors = {}
            for task_id in ordered_ids:
                own_duration = task_by_id[task_id].allocated_hours or 0.0
                dependency_ids = predecessors[task_id]
                if not dependency_ids:
                    duration_by_task[task_id] = own_duration
                    best_predecessors[task_id] = []
                    continue
                best_duration = max(duration_by_task[dependency_id] for dependency_id in dependency_ids)
                duration_by_task[task_id] = best_duration + own_duration
                best_predecessors[task_id] = sorted(
                    dependency_id
                    for dependency_id in dependency_ids
                    if duration_by_task[dependency_id] == best_duration
                )

            end_ids = [task_id for task_id in ordered_ids if not successors[task_id]]
            maximum_duration = max((duration_by_task[task_id] for task_id in end_ids), default=0.0)
            critical_end_ids = [
                task_id for task_id in end_ids if duration_by_task[task_id] == maximum_duration
            ]

            def build_paths(task_id):
                if not best_predecessors[task_id]:
                    return [[task_id]]
                return [
                    path + [task_id]
                    for predecessor_id in best_predecessors[task_id]
                    for path in build_paths(predecessor_id)
                ]

            critical_paths = [
                path for end_id in critical_end_ids for path in build_paths(end_id)
            ]
            Path.search([("project_id", "=", project.id)]).unlink()
            Path.create([
                {
                    "project_id": project.id,
                    "sequence": index * 10,
                    "name": "CP-%02d" % index,
                    "duration": maximum_duration,
                    "task_ids": [(6, 0, path)],
                    "task_path": " → ".join(task_by_id[task_id].display_name for task_id in path),
                }
                for index, path in enumerate(critical_paths, start=1)
            ])
            project.write({
                "critical_path_count": len(critical_paths),
                "critical_path_duration": maximum_duration,
            })
