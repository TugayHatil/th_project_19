# -*- coding: utf-8 -*-

import json
from collections import deque
from datetime import timedelta

from odoo import _, api, fields, models
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
    # Per-project planning precision (BRD Planning Precision). ``hour`` is
    # the existing behaviour — the Planner keeps date+time inputs and
    # hour-granularity drags. ``day`` hides the time pickers and quantizes
    # drags/resizes to whole calendar days. Display + input precision only;
    # the datetime storage and the scheduling engine stay untouched.
    planning_precision = fields.Selection(
        [("hour", "Hour"), ("day", "Day")],
        string="Planning Precision",
        default="hour",
        required=True,
    )

    def _get_baseline_resource_vals(self):
        """Resource-planning snapshot values for a new baseline.

        Hook kept deliberately empty in the core addon — the
        ``project_resource_planning`` addon overrides it with the real
        planned hours/cost. Standalone core stores zeros, so baselines
        work identically whether or not the resource addon is installed.
        """
        self.ensure_one()
        return {
            "planned_resource_hours": 0.0,
            "planned_resource_cost": 0.0,
            "currency_id": False,
        }

    def _compute_critical_path_baseline_count(self):
        for project in self:
            project.critical_path_baseline_count = len(project.critical_path_baseline_ids)

    def action_calculate_critical_paths(self):
        self._recalculate_critical_paths()
        return True

    def action_create_critical_path_baseline(self, baseline_label=None):
        """Freeze the calculated plan as the next immutable baseline revision.

        ``baseline_label`` is an optional user-provided name appended to the
        auto-generated version — ``v1.20 - Revize İş Programı``. Callers that
        pass no label keep the plain ``v1.X`` naming (BRD Baseline Save).
        """
        Baseline = self.env["project.critical.path.baseline"]
        label = (baseline_label or "").strip()
        for project in self:
            project._recalculate_critical_paths()
            previous_baseline = Baseline.search(
                [("project_id", "=", project.id)], order="revision_number desc, id desc", limit=1,
            )
            revision_number = previous_baseline.revision_number + 1 if previous_baseline else 0
            name = "v1.%d" % revision_number
            if label:
                name = "%s - %s" % (name, label)
            baseline = Baseline.create({
                "project_id": project.id,
                "revision_number": revision_number,
                "name": name,
                "project_duration": project.critical_path_duration,
                "critical_path_duration": project.critical_path_duration,
                **project._get_baseline_resource_vals(),
                "critical_path_signature": project._get_critical_path_signature(),
                "critical_path_snapshot": json.dumps([
                    {
                        "task_ids": path.task_ids.ids,
                        "task_path": path.task_path,
                        "tasks": [
                            {"id": task.id, "name": task.display_name} for task in path.task_ids
                        ],
                    }
                    for path in project.critical_path_ids
                ]),
            })
            baseline._create_snapshot_lines()
            project._recalculate_delay_impacts()
            baseline._recalculate_critical_path_changes()
            baseline._recalculate_history_comparisons()
        return True

    def action_view_critical_path_baselines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Plan Baselines"),
            "res_model": "project.critical.path.baseline",
            "view_mode": "list,form",
            "views": [[False, "list"], [False, "form"]],
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
            # best_predecessors retains every predecessor whose edge bound
            # actually produced that finish (type- and lag-aware — with
            # FS+0 edges this is exactly "the longest finishing parent").
            duration_by_task = schedule["early_finish"]
            best_predecessors = {}
            for task_id in ordered_ids:
                dependency_edges = predecessors[task_id]
                duration = task_by_id[task_id].allocated_hours or 0.0
                best_predecessors[task_id] = sorted(
                    dependency_id
                    for dependency_id, edge in dependency_edges.items()
                    if abs(
                        self._edge_early_bound(
                            edge,
                            duration_by_task[dependency_id]
                            - (task_by_id[dependency_id].allocated_hours or 0.0),
                            duration_by_task[dependency_id],
                            duration,
                        )
                        - duration_by_task[task_id]
                    ) < 0.000001
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
            project.critical_path_baseline_ids._recalculate_history_comparisons()

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
        # WBS parents keep a baseline snapshot but are excluded from the
        # leaf-only schedule graph, so they have no ``successors`` entry.
        while successors.get(current_id):
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

    def _ensure_dependency_records(self):
        """Reconcile ``project.task.dependency`` rows with the M2M edges.

        ``depend_on_ids`` is the structural source of truth — every write
        path (Inspector, gantt, imports, code) goes through it. This lazy
        reconciliation keeps exactly one attribute row per edge so the
        relationship type and lag always exist for the schedule and the
        planner payload. Returns ``{(task_id, depends_on_id): record}``.
        """
        self.ensure_one()
        Dependency = self.env["project.task.dependency"].sudo()
        tasks = self.env["project.task"].with_context(active_test=False).search(
            [("project_id", "=", self.id)]
        )
        wanted = {
            (task.id, dependency.id)
            for task in tasks
            for dependency in task.depend_on_ids
            if dependency.id != task.id
        }
        existing = Dependency.search([("project_id", "=", self.id)])
        orphans = existing.filtered(
            lambda row: (row.task_id.id, row.depends_on_id.id) not in wanted
        )
        if orphans:
            orphans.unlink()
        existing -= orphans
        have = {(row.task_id.id, row.depends_on_id.id) for row in existing}
        missing = wanted - have
        if missing:
            Dependency.create(
                [
                    {"task_id": task_id, "depends_on_id": depends_on_id}
                    for task_id, depends_on_id in sorted(missing)
                ]
            )
            existing = Dependency.search([("project_id", "=", self.id)])
        return {(row.task_id.id, row.depends_on_id.id): row for row in existing}

    def _get_task_dependency_graph(self):
        """Return the standard task dependency graph once for all calculations.

        Every task is a schedulable node carrying its own allocated_hours and
        its own dependencies — WBS hierarchy is a presentation concern only
        and must not change the critical path. Edges are the plain
        ``depend_on_ids`` links restricted to this project; a self-link is
        dropped since it can never affect the schedule. Each edge carries the
        ``project.task.dependency`` attributes — relationship type and lag in
        hours — so the CPM passes can honour FS/SS/FF/SF and lead/lag.
        """
        self.ensure_one()
        tasks = self.env["project.task"].with_context(active_test=False).search(
            [("project_id", "=", self.id)], order="id",
        )
        task_by_id = {task.id: task for task in tasks}
        task_ids = set(task_by_id)
        dependency_rows = self._ensure_dependency_records()

        def edge(task_id, dependency_id):
            row = dependency_rows.get((task_id, dependency_id))
            return {
                "type": row.relationship_type if row else "fs",
                "lag": row.lag_hours if row else 0.0,
            }

        predecessors = {
            task.id: {
                dependency.id: edge(task.id, dependency.id)
                for dependency in task.depend_on_ids
                if dependency.id in task_by_id and dependency.id != task.id
            }
            for task in tasks
        }
        successors = {task_id: {} for task_id in task_ids}
        for task_id, dependency_ids in predecessors.items():
            for dependency_id, dependency_edge in dependency_ids.items():
                successors[dependency_id][task_id] = dependency_edge

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
        if len(ordered_ids) != len(task_ids):
            raise UserError(_("Critical paths cannot be calculated because task dependencies contain a cycle."))

        return {
            "task_by_id": task_by_id,
            "predecessors": predecessors,
            "successors": successors,
            "ordered_ids": ordered_ids,
            "end_ids": [task_id for task_id in ordered_ids if not successors[task_id]],
        }

    @staticmethod
    def _edge_early_bound(edge, pred_es, pred_ef, duration):
        """Forward-pass lower bound this edge puts on the successor's EF."""
        lag = edge["lag"]
        relation = edge["type"]
        if relation == "ss":
            return pred_es + lag + duration
        if relation == "ff":
            return pred_ef + lag
        if relation == "sf":
            return pred_es + lag
        return pred_ef + lag + duration  # fs

    @staticmethod
    def _edge_late_bound(edge, succ_ls, succ_lf, duration):
        """Backward-pass upper bound this edge puts on the predecessor's LF."""
        lag = edge["lag"]
        relation = edge["type"]
        if relation == "ss":
            return succ_ls - lag + duration
        if relation == "ff":
            return succ_lf - lag
        if relation == "sf":
            return succ_lf - lag + duration
        return succ_ls - lag  # fs

    def _calculate_task_schedule(self, graph):
        """Run CPM forward/backward passes over the shared dependency graph.

        Edges carry a relationship type and a lag in hours (BRD Dependency
        Lag). With the default FS+0 every bound collapses to the classic
        formulas, so existing plans compute identically.
        """
        task_by_id = graph["task_by_id"]
        predecessors = graph["predecessors"]
        successors = graph["successors"]
        ordered_ids = graph["ordered_ids"]
        end_ids = graph["end_ids"]

        early_start, early_finish = {}, {}
        for task_id in ordered_ids:
            duration = task_by_id[task_id].allocated_hours or 0.0
            # EF >= duration keeps the early start non-negative.
            finish_bound = duration
            for dependency_id, edge in predecessors[task_id].items():
                pred_ef = early_finish[dependency_id]
                pred_es = pred_ef - (task_by_id[dependency_id].allocated_hours or 0.0)
                finish_bound = max(
                    finish_bound,
                    self._edge_early_bound(edge, pred_es, pred_ef, duration),
                )
            early_finish[task_id] = finish_bound
            early_start[task_id] = finish_bound - duration

        project_duration = max((early_finish[task_id] for task_id in end_ids), default=0.0)
        late_start, late_finish = {}, {}
        for task_id in reversed(ordered_ids):
            duration = task_by_id[task_id].allocated_hours or 0.0
            finish_bound = project_duration
            for successor_id, edge in successors[task_id].items():
                succ_lf = late_finish[successor_id]
                succ_ls = succ_lf - (task_by_id[successor_id].allocated_hours or 0.0)
                finish_bound = min(
                    finish_bound,
                    self._edge_late_bound(edge, succ_ls, succ_lf, duration),
                )
            late_finish[task_id] = finish_bound
            late_start[task_id] = finish_bound - duration

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

    def _schedule_dependents(self, changed_tasks):
        """Push tasks forward when a dependency bound is violated.

        BRD Dependency-Based Auto Scheduling: bounds are evaluated at
        datetime precision — the Planner's day scale edits real clock
        times, and a 24h-style chain like A 09:00–17:00 → B 17:00–… must
        shift by exact hours, not whole days:

        * FS → successor starts ≥ predecessor finish + lag
        * SS → successor starts ≥ predecessor start + lag
        * FF → successor finishes ≥ predecessor finish + lag
        * SF → successor finishes ≥ predecessor start + lag

        The changed tasks themselves are validated against their own
        predecessors — a task dragged before its earliest valid start is
        pushed back to it — and every downstream task is checked in
        topological order so each predecessor is final (possibly already
        shifted) before its successors are evaluated. A task whose plan
        already honours every bound is left alone; a violating task is
        shifted forward by exactly the tightest bound, keeping its
        start→finish span. Shifts write with ``cp_skip_auto_schedule`` so
        the cascade runs in this single pass instead of re-entering
        through ``write``.
        """
        self.ensure_one()
        graph = self._get_task_dependency_graph()
        task_by_id = graph["task_by_id"]
        successors = graph["successors"]

        # The check set is the changed tasks plus everything downstream —
        # BFS over the successor map.
        check = set(changed_tasks.ids)
        queue = deque(
            successor_id
            for task in changed_tasks
            for successor_id in successors.get(task.id, {})
        )
        while queue:
            task_id = queue.popleft()
            if task_id in check:
                continue
            check.add(task_id)
            queue.extend(successors.get(task_id, {}))
        if not check:
            return

        # Effective (start, stop) per task — shifted values feed the bounds
        # of downstream tasks so the whole chain resolves in one pass.
        effective = {}

        def times(task):
            if task.id in effective:
                return effective[task.id]
            if not task.date_assign or not task.date_deadline:
                return None  # unscheduled tasks give/receive no bound
            return (task.date_assign, task.date_deadline)

        shifted = []
        for task_id in graph["ordered_ids"]:
            if task_id not in check:
                continue
            task = task_by_id[task_id]
            current = times(task)
            if not current:
                continue
            # WBS parents mirror their dated children via _sync_parent_window —
            # auto-shifting them for their own dependency bounds would clobber
            # the rolled-up window. Their successors are still checked against
            # the parent's current window.
            if task.child_ids:
                continue
            start, stop = current
            span = stop - start
            required_start = start  # bounds only ever push forward
            for dependency_id, edge in graph["predecessors"][task_id].items():
                pred = times(task_by_id[dependency_id])
                if not pred:
                    continue
                pred_start, pred_stop = pred
                lag = timedelta(hours=edge["lag"])
                relation = edge["type"]
                if relation == "ss":
                    bound = pred_start + lag
                elif relation == "ff":
                    bound = pred_stop + lag - span
                elif relation == "sf":
                    bound = pred_start + lag - span
                else:  # fs
                    bound = pred_stop + lag
                if bound > required_start:
                    required_start = bound
            if required_start > start:
                effective[task.id] = (required_start, required_start + span)
                shifted.append(task)

        if not shifted:
            return
        for task in shifted:
            start, stop = effective[task.id]
            task.with_context(cp_skip_auto_schedule=True).write(
                {"date_assign": start, "date_deadline": stop}
            )
        self._recalculate_critical_paths()
