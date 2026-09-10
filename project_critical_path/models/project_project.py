# -*- coding: utf-8 -*-

import json
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
    critical_path_baseline_ids = fields.One2many(
        "project.critical.path.baseline", "project_id", string="Baselines", readonly=True,
    )
    critical_path_baseline_count = fields.Integer(
        string="Baseline Count", compute="_compute_critical_path_baseline_count",
    )
    delay_impact_baseline_id = fields.Many2one(
        "project.critical.path.baseline", string="Impact Baseline", readonly=True,
    )
    delay_baseline_duration = fields.Float(string="Baseline Duration", readonly=True)
    delay_current_duration = fields.Float(string="Current Duration", readonly=True)
    delay_total = fields.Float(string="Total Delay", readonly=True)
    delay_impact_line_ids = fields.One2many(
        "project.task.delay.impact", "project_id", string="Delay Impact Summary", readonly=True,
    )

    def _compute_critical_path_baseline_count(self):
        for project in self:
            project.critical_path_baseline_count = len(project.critical_path_baseline_ids)

    def action_calculate_critical_paths(self):
        self._recalculate_critical_paths()
        return True

    def action_create_critical_path_baseline(self):
        """Freeze the calculated plan as the next immutable baseline revision."""
        Baseline = self.env["project.critical.path.baseline"]
        for project in self:
            project._recalculate_critical_paths()
            previous_baseline = Baseline.search(
                [("project_id", "=", project.id)], order="revision_number desc, id desc", limit=1,
            )
            revision_number = previous_baseline.revision_number + 1 if previous_baseline else 0
            baseline = Baseline.create({
                "project_id": project.id,
                "revision_number": revision_number,
                "name": "v1.%d" % revision_number,
                "project_duration": project.critical_path_duration,
                "critical_path_duration": project.critical_path_duration,
                "critical_path_signature": project._get_critical_path_signature(),
                "critical_path_snapshot": json.dumps([
                    {"task_ids": path.task_ids.ids, "task_path": path.task_path}
                    for path in project.critical_path_ids
                ]),
            })
            baseline._create_snapshot_lines()
            project._recalculate_delay_impacts()
            baseline._recalculate_critical_path_changes()
        return True

    def action_view_critical_path_baselines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Plan Baselines"),
            "res_model": "project.critical.path.baseline",
            "view_mode": "list,form",
            "domain": [("project_id", "=", self.id)],
            "context": {"default_project_id": self.id, "create": False},
        }

    def _get_critical_path_signature(self):
        self.ensure_one()
        return "\n".join(sorted(self.critical_path_ids.mapped("task_path")))

    def _recalculate_critical_paths(self):
        """Rebuild saved critical paths using only this project's task graph.

        A task's ``allocated_hours`` is the Odoo 19 planned/allocated duration.
        The algorithm is a longest-path dynamic programme over the dependency DAG.
        All ties are retained, so multiple critical paths are saved.
        """
        for project in self:
            graph = project._get_task_dependency_graph()
            task_by_id = graph["task_by_id"]
            predecessors = graph["predecessors"]
            successors = graph["successors"]
            ordered_ids = graph["ordered_ids"]
            end_ids = graph["end_ids"]
            schedule = project._calculate_task_schedule(graph)
            for task_id, values in schedule["task_values"].items():
                task_by_id[task_id].write(values)

            # duration_by_task is the longest duration ending at each task;
            # best_predecessors retains every predecessor that yields that value.
            duration_by_task = schedule["early_finish"]
            best_predecessors = {}
            for task_id in ordered_ids:
                dependency_ids = predecessors[task_id]
                if not dependency_ids:
                    best_predecessors[task_id] = []
                    continue
                best_duration = max(
                    duration_by_task[dependency_id] for dependency_id in dependency_ids
                )
                best_predecessors[task_id] = sorted(
                    dependency_id
                    for dependency_id in dependency_ids
                    if duration_by_task[dependency_id] == best_duration
                )

            maximum_duration = schedule["project_duration"]
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
            Path = self.env["project.critical.path"].sudo()
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
            project._recalculate_delay_impacts()
            project.critical_path_baseline_ids._recalculate_critical_path_changes()

    def _recalculate_delay_impacts(self):
        """Compare current task durations with the newest frozen plan revision."""
        Impact = self.env["project.task.delay.impact"]
        Baseline = self.env["project.critical.path.baseline"]
        for project in self:
            baseline = Baseline.search(
                [("project_id", "=", project.id)], order="revision_number desc, id desc", limit=1,
            )
            tasks = self.env["project.task"].with_context(active_test=False).search(
                [("project_id", "=", project.id)], order="id",
            )
            Impact.search([("project_id", "=", project.id)]).unlink()
            if not baseline:
                tasks.write({
                    "delay_baseline_duration": 0.0,
                    "delay_duration_variance": 0.0,
                    "delay_project_impact": 0.0,
                    "delay_impact_status": "no_impact",
                    "delay_impact_chain": False,
                })
                project.write({
                    "delay_impact_baseline_id": False,
                    "delay_baseline_duration": 0.0,
                    "delay_current_duration": project.critical_path_duration,
                    "delay_total": 0.0,
                })
                continue

            graph = project._get_task_dependency_graph()
            task_by_id = graph["task_by_id"]
            successors = graph["successors"]
            baseline_by_task_id = {line.task_id.id: line for line in baseline.line_ids if line.task_id}
            total_delay = project.critical_path_duration - baseline.project_duration
            task_values, impact_values = {}, []
            for task in tasks:
                snapshot = baseline_by_task_id.get(task.id)
                if not snapshot:
                    values = {
                        "delay_baseline_duration": 0.0,
                        "delay_duration_variance": task.allocated_hours or 0.0,
                        "delay_project_impact": 0.0,
                        "delay_impact_status": "no_impact",
                        "delay_impact_chain": False,
                    }
                else:
                    variance = (task.allocated_hours or 0.0) - snapshot.allocated_hours
                    if variance > 0.000001:
                        impact = min(
                            max(0.0, variance - max(0.0, snapshot.slack)),
                            max(0.0, total_delay),
                        )
                        status = "critical_impact" if impact > 0.000001 else "within_slack"
                    elif variance < -0.000001:
                        impact = -min(abs(variance), max(0.0, -total_delay))
                        status = "duration_reduced"
                    else:
                        impact, status = 0.0, "no_impact"
                    values = {
                        "delay_baseline_duration": snapshot.allocated_hours,
                        "delay_duration_variance": variance,
                        "delay_project_impact": impact,
                        "delay_impact_status": status,
                        "delay_impact_chain": project._get_delay_impact_chain(
                            task.id, impact, graph, baseline_by_task_id,
                        ) if abs(impact) > 0.000001 else False,
                    }
                task_values[task.id] = values

            for task in tasks:
                task.write(task_values[task.id])
                values = task_values[task.id]
                if task.id in baseline_by_task_id:
                    impact_values.append({
                        "project_id": project.id,
                        "baseline_id": baseline.id,
                        "task_id": task.id,
                        "sequence": 0 if abs(values["delay_project_impact"]) > 0.000001 else 10,
                        "baseline_duration": values["delay_baseline_duration"],
                        "current_duration": task.allocated_hours or 0.0,
                        "duration_variance": values["delay_duration_variance"],
                        "project_impact": values["delay_project_impact"],
                        "impact_status": values["delay_impact_status"],
                        "impact_chain": values["delay_impact_chain"],
                    })
            if impact_values:
                Impact.create(impact_values)
            project.write({
                "delay_impact_baseline_id": baseline.id,
                "delay_baseline_duration": baseline.project_duration,
                "delay_current_duration": project.critical_path_duration,
                "delay_total": total_delay,
            })

    def _get_delay_impact_chain(self, task_id, impact, graph, baseline_by_task_id):
        """Return one readable downstream chain for a task that changes the finish."""
        self.ensure_one()
        task_by_id = graph["task_by_id"]
        successors = graph["successors"]
        current_id = task_id
        steps = ["%s (%+.2f h)" % (task_by_id[task_id].display_name, impact)]
        seen = {task_id}
        while successors[current_id]:
            candidates = [
                successor_id for successor_id in successors[current_id]
                if successor_id not in seen
                and successor_id in baseline_by_task_id
                and task_by_id[successor_id].critical_early_start
                > baseline_by_task_id[successor_id].early_start + 0.000001
            ]
            if not candidates:
                break
            current_id = max(
                candidates, key=lambda successor_id: task_by_id[successor_id].critical_early_finish,
            )
            seen.add(current_id)
            shift = (
                task_by_id[current_id].critical_early_start
                - baseline_by_task_id[current_id].early_start
            )
            steps.append("%s start %+.2f h" % (task_by_id[current_id].display_name, shift))
        steps.append("Project finish %+.2f h" % impact)
        return " → ".join(steps)

    def _get_task_dependency_graph(self):
        """Return the standard task dependency graph once for all calculations."""
        self.ensure_one()
        tasks = self.env["project.task"].with_context(active_test=False).search(
            [("project_id", "=", self.id)], order="id",
        )
        task_by_id = {task.id: task for task in tasks}
        task_ids = set(task_by_id)
        predecessors = {
            task.id: {dependency.id for dependency in task.depend_on_ids if dependency.id in task_ids}
            for task in tasks
        }
        successors = {task_id: set() for task_id in task_ids}
        for task_id, dependency_ids in predecessors.items():
            for dependency_id in dependency_ids:
                successors[dependency_id].add(task_id)

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

        return {
            "task_by_id": task_by_id,
            "predecessors": predecessors,
            "successors": successors,
            "ordered_ids": ordered_ids,
            "end_ids": [task_id for task_id in ordered_ids if not successors[task_id]],
        }

    def _calculate_task_schedule(self, graph):
        """Run CPM forward/backward passes over the shared dependency graph."""
        task_by_id = graph["task_by_id"]
        predecessors = graph["predecessors"]
        successors = graph["successors"]
        ordered_ids = graph["ordered_ids"]
        end_ids = graph["end_ids"]

        early_start, early_finish = {}, {}
        for task_id in ordered_ids:
            early_start[task_id] = max(
                (early_finish[dependency_id] for dependency_id in predecessors[task_id]),
                default=0.0,
            )
            early_finish[task_id] = early_start[task_id] + (task_by_id[task_id].allocated_hours or 0.0)

        project_duration = max((early_finish[task_id] for task_id in end_ids), default=0.0)
        late_start, late_finish = {}, {}
        for task_id in reversed(ordered_ids):
            late_finish[task_id] = min(
                (late_start[successor_id] for successor_id in successors[task_id]),
                default=project_duration,
            )
            late_start[task_id] = late_finish[task_id] - (task_by_id[task_id].allocated_hours or 0.0)

        return {
            "early_finish": early_finish,
            "project_duration": project_duration,
            "task_values": {
                task_id: {
                    "critical_early_start": early_start[task_id],
                    "critical_early_finish": early_finish[task_id],
                    "critical_late_start": late_start[task_id],
                    "critical_late_finish": late_finish[task_id],
                    "critical_slack": late_start[task_id] - early_start[task_id],
                    "is_critical": abs(late_start[task_id] - early_start[task_id]) < 0.000001,
                }
                for task_id in ordered_ids
            },
        }
