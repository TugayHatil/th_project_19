# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import api, fields, models

from odoo.addons.project_critical_path.models.project_planner import (
    _planner_hours_per_day,
)


class ProjectProject(models.Model):
    """Project-level actual KPIs (BRD §5).

    All values derive from the task set in a single search — no per-task
    queries (BRD §29). Completion reuses the WBS roll-up convention from
    project_critical_path: allocated-hours weighted progress, plain
    average when nothing carries hours.
    """

    _inherit = "project.project"

    actual_task_count = fields.Integer(
        string="Total Tasks", compute="_compute_actual_summary",
    )
    actual_done_task_count = fields.Integer(
        string="Completed Tasks", compute="_compute_actual_summary",
    )
    actual_in_progress_task_count = fields.Integer(
        string="In Progress Tasks", compute="_compute_actual_summary",
    )
    actual_not_started_task_count = fields.Integer(
        string="Not Started Tasks", compute="_compute_actual_summary",
    )
    actual_completion = fields.Float(
        string="Project Completion (%)", compute="_compute_actual_summary",
        digits=(16, 1),
    )
    actual_span_hours = fields.Float(
        string="Actual Duration", compute="_compute_actual_summary",
        digits=(16, 2),
    )
    actual_finish_variance_days = fields.Integer(
        string="Project Finish Variance (Days)",
        compute="_compute_actual_summary",
    )
    actual_delayed_task_count = fields.Integer(
        string="Delayed Tasks", compute="_compute_actual_summary",
    )
    actual_critical_delayed_task_count = fields.Integer(
        string="Critical Delayed Tasks", compute="_compute_actual_summary",
    )

    # ---- Material impact KPIs (BRD §24) -------------------------------------
    material_risk_task_count = fields.Integer(
        string="Material Risk Tasks", compute="_compute_material_summary",
    )
    material_delayed_task_count = fields.Integer(
        string="Material Delayed Tasks", compute="_compute_material_summary",
    )
    material_critical_delay_task_count = fields.Integer(
        string="Critical Material Delays", compute="_compute_material_summary",
    )
    material_shortage_line_count = fields.Integer(
        string="Material Shortage Lines", compute="_compute_material_summary",
    )
    material_planned_finish = fields.Date(
        string="Planned Finish", compute="_compute_material_summary",
    )
    material_projected_finish = fields.Date(
        string="Material-Projected Finish", compute="_compute_material_summary",
    )
    material_finish_impact_days = fields.Float(
        string="Material Finish Impact (Days)",
        compute="_compute_material_summary", digits=(16, 1),
    )

    # ---- Skill-match KPIs (BRD §7/§24) --------------------------------------
    skill_required_task_count = fields.Integer(
        string="Tasks With Skill Requirements",
        compute="_compute_skill_summary",
    )
    skill_matched_task_count = fields.Integer(
        string="Skill Matched Tasks", compute="_compute_skill_summary",
    )
    skill_partial_task_count = fields.Integer(
        string="Partial Skill Match Tasks", compute="_compute_skill_summary",
    )
    skill_unmatched_task_count = fields.Integer(
        string="Skill Unmatched Tasks", compute="_compute_skill_summary",
    )

    def _compute_actual_summary(self):
        tasks = self.env["project.task"].with_context(active_test=False).search(
            [("project_id", "in", self.ids)]
        )
        by_project = defaultdict(lambda: self.env["project.task"])
        for task in tasks:
            by_project[task.project_id.id] |= task
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        for project in self:
            project_tasks = by_project.get(project.id) or self.env["project.task"]
            total = len(project_tasks)
            done = in_progress = not_started = delayed = critical_delayed = 0
            weighted = planned = progress_sum = 0.0
            starts, finishes, deadlines = [], [], []
            for task in project_tasks:
                if task.actual_status == "done":
                    done += 1
                elif task.actual_status == "in_progress":
                    in_progress += 1
                else:
                    not_started += 1
                hours = task.allocated_hours or 0.0
                weighted += (task.progress or 0.0) * hours
                planned += hours
                progress_sum += task.progress or 0.0
                if task.date_actual_start:
                    starts.append(task.date_actual_start)
                if task.actual_finish:
                    finishes.append(
                        fields.Datetime.context_timestamp(
                            task, task.actual_finish
                        ).date()
                    )
                if task.date_deadline:
                    deadlines.append(
                        fields.Datetime.context_timestamp(
                            task, task.date_deadline
                        ).date()
                    )
                is_delayed = task.schedule_variance_state == "late" or (
                    task.state != "1_done"
                    and task.date_deadline
                    and fields.Datetime.context_timestamp(
                        task, task.date_deadline
                    ).date() < today
                )
                if is_delayed:
                    delayed += 1
                    critical_delayed += int(bool(task.is_critical))
            project.actual_task_count = total
            project.actual_done_task_count = done
            project.actual_in_progress_task_count = in_progress
            project.actual_not_started_task_count = not_started
            if planned > 0:
                project.actual_completion = weighted / planned * 100.0
            elif total:
                project.actual_completion = progress_sum / total * 100.0
            else:
                project.actual_completion = 0.0
            if starts:
                # In-flight projects get an open-ended span: earliest actual
                # start to the latest actual finish, or to now when nothing
                # has finished yet.
                latest_finish = (
                    max(project_tasks.filtered("actual_finish").mapped(
                        "actual_finish"))
                    if finishes else now
                )
                project.actual_span_hours = (
                    latest_finish - min(starts)
                ).total_seconds() / 3600.0
            else:
                project.actual_span_hours = 0.0
            project.actual_finish_variance_days = (
                (max(finishes) - max(deadlines)).days
                if finishes and deadlines else False
            )
            project.actual_delayed_task_count = delayed
            project.actual_critical_delayed_task_count = critical_delayed

    # ---- Material impact -----------------------------------------------------

    def _propagate_start_delay(self, graph, schedule, task_id, shift_hours):
        """What-if forward pass: ``task_id`` starts/finishes ``shift_hours``
        later and every bound violation propagates downstream.

        Reuses the shared engine pieces verbatim — the dependency graph
        (``_get_task_dependency_graph``), the edge semantics
        (``_edge_early_bound``) and the CPM schedule output — this is a
        perturbation of the stored schedule, not a second engine. Nothing
        is written back to the plan.

        Returns ``(downstream_deltas, project_delta)`` — hours shifted per
        affected downstream task and the project-duration delta.
        """
        ordered_ids = graph["ordered_ids"]
        predecessors = graph["predecessors"]
        task_by_id = graph["task_by_id"]
        duration = {
            t: task_by_id[t].allocated_hours or 0.0 for t in ordered_ids
        }
        es = {
            t: schedule["task_values"][t]["critical_early_start"]
            for t in ordered_ids
        }
        ef = {
            t: schedule["task_values"][t]["critical_early_finish"]
            for t in ordered_ids
        }
        p_es, p_ef = dict(es), dict(ef)
        p_es[task_id] += shift_hours
        p_ef[task_id] += shift_hours
        perturbed = {task_id}
        reached = False
        for tid in ordered_ids:
            if tid == task_id:
                reached = True
                continue
            if not reached or not (perturbed & set(predecessors[tid])):
                continue
            new_ef = ef[tid]
            for pred_id, edge in predecessors[tid].items():
                bound = self._edge_early_bound(
                    edge, p_es[pred_id], p_ef[pred_id], duration[tid])
                if bound > new_ef:
                    new_ef = bound
            if new_ef > ef[tid] + 0.000001:
                p_ef[tid] = new_ef
                p_es[tid] = new_ef - duration[tid]
                perturbed.add(tid)
        deltas = {
            t: p_ef[t] - ef[t] for t in perturbed if t != task_id
        }
        project_delta = max(
            (p_ef[e] for e in graph["end_ids"]), default=0.0
        ) - schedule["project_duration"]
        return deltas, project_delta

    def _compute_material_summary(self):
        for project in self:
            tasks = project.task_ids.with_context(active_test=False)
            tasks.mapped("material_risk")  # one batched compute
            risky = tasks.filtered(lambda t: t.material_risk != "no_risk")
            delayed = tasks.filtered(lambda t: t.material_risk == "delayed")
            critical = tasks.filtered(
                lambda t: t.material_risk == "critical")
            project.material_risk_task_count = len(risky)
            project.material_delayed_task_count = len(delayed)
            project.material_critical_delay_task_count = len(critical)
            project.material_shortage_line_count = len(
                tasks.material_plan_line_ids.filtered(
                    lambda l: l.shortage_quantity > 0.000001
                    or l.material_state == "unknown"
                )
            )
            deadlines = [
                fields.Datetime.context_timestamp(
                    task, task.date_deadline).date()
                for task in tasks if task.date_deadline
            ]
            planned_finish = max(deadlines) if deadlines else False
            impact = max(
                tasks.mapped("material_project_impact_days"), default=0.0)
            project.material_planned_finish = planned_finish
            project.material_finish_impact_days = impact
            project.material_projected_finish = (
                fields.Date.add(planned_finish, days=int(round(impact)))
                if planned_finish else False
            )

    def _compute_skill_summary(self):
        for project in self:
            tasks = project.task_ids.with_context(active_test=False)
            tasks.mapped("skill_match_state")  # one batched compute
            required = tasks.filtered(
                lambda t: t.skill_match_state != "not_required")
            project.skill_required_task_count = len(required)
            project.skill_matched_task_count = len(
                required.filtered(lambda t: t.skill_match_state == "matched"))
            project.skill_partial_task_count = len(
                required.filtered(lambda t: t.skill_match_state == "partial"))
            project.skill_unmatched_task_count = len(
                required.filtered(lambda t: t.skill_match_state == "unmatched"))

    # ---- Planner payload ---------------------------------------------------

    def get_planner_data(self, baseline_id=None, domain=None):
        """Inject the actual-tracking and material-risk blocks into every
        task row.

        Done as payload post-processing rather than through the
        ``_planner_resource_fields`` hook on purpose: nothing orders this
        addon's model methods after ``project_resource_planning``'s —
        whose hook override does not call ``super()`` and would silently
        swallow ours whenever it loads last.
        """
        data = super().get_planner_data(baseline_id=baseline_id, domain=domain)
        rows = {
            row["id"]: row
            for row in data.get("tasks") or []
            if isinstance(row, dict) and row.get("id")
        }
        if rows:
            tasks = self.env["project.task"].browse(list(rows)).exists()
            # One batched material compute — a per-row read would rebuild
            # the dependency graph for every task in the payload.
            tasks.mapped("material_risk")
            tasks.mapped("skill_match_state")
            for task in tasks:
                rows[task.id].update(task._planner_actual_fields())
                rows[task.id].update(task._planner_material_fields())
                rows[task.id].update(task._planner_skill_fields())
        return data
