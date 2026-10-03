# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import api, fields, models


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
