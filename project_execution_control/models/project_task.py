# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.project_critical_path.models.project_planner import (
    _planner_hours_per_day,
    _serialize_planner_day,
    _serialize_planner_dt,
)


def _actual_window_hours(task):
    """Actual duration from the actual window — same convention the Planner
    applies to planned bars and ``_task_window_hours``: a same-day span is
    its real hour length, a multi-day span is day-count x calendar
    hours-per-day. Returns 0 until both an actual start and an actual
    finish exist (BRD §28: no partial data, no duration)."""
    start = task.date_actual_start
    stop = task.actual_finish
    if not start or not stop or stop <= start:
        return 0.0
    if start.date() == stop.date():
        return (stop - start).total_seconds() / 3600.0
    return (
        (stop.date() - start.date()).days + 1
    ) * _planner_hours_per_day(task)


class ProjectTask(models.Model):
    """Actual execution fields on top of the planned schedule.

    ``date_done`` / ``finish_variance_state`` from project_critical_path
    stay untouched — they keep tracking the Odoo "done" state. The manual
    ``date_actual_*`` pair is the user-entered actual data; ``actual_finish``
    resolves the single effective finish (manual entry wins, the done
    stamp is the fallback) that every downstream compute reads.
    """

    _inherit = "project.task"

    date_actual_start = fields.Datetime(
        string="Actual Start", copy=False, tracking=True,
    )
    date_actual_end = fields.Datetime(
        string="Actual End", copy=False, tracking=True,
    )
    actual_finish = fields.Datetime(
        string="Actual Finish",
        compute="_compute_actual_finish", store=True, readonly=True, copy=False,
    )
    actual_duration = fields.Float(
        string="Actual Duration", compute="_compute_actual_values",
        store=True, readonly=True, digits=(16, 2),
    )
    # Stored so Planner/search filters can use it as a domain leaf.
    actual_status = fields.Selection(
        [
            ("not_started", "Not Started"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
        ],
        string="Actual Status", compute="_compute_actual_values",
        store=True, readonly=True, index=True,
    )
    # Schedule Variance (BRD §4.6): whole-day comparison of the effective
    # actual finish against the planned deadline — same convention as the
    # core finish_variance_state, but driven by actual_finish so a manual
    # actual end is honoured even before the task is closed.
    schedule_variance_days = fields.Integer(
        string="Schedule Variance (Days)",
        compute="_compute_actual_values", store=True, readonly=True,
    )
    schedule_variance_state = fields.Selection(
        [
            ("early", "Completed Early"),
            ("on_time", "Completed On Time"),
            ("late", "Completed Late"),
        ],
        string="Schedule Variance",
        compute="_compute_actual_values", store=True, readonly=True, index=True,
    )

    @api.depends("date_actual_end", "date_done")
    def _compute_actual_finish(self):
        for task in self:
            task.actual_finish = task.date_actual_end or task.date_done

    @api.depends(
        "state", "date_actual_start", "date_actual_end", "actual_finish",
        "date_deadline", "effective_hours",
    )
    def _compute_actual_values(self):
        for task in self:
            task.actual_duration = _actual_window_hours(task)
            if task.actual_finish:
                task.actual_status = "done"
            elif task.date_actual_start or (task.effective_hours or 0.0) > 0:
                task.actual_status = "in_progress"
            else:
                task.actual_status = "not_started"
            if task.actual_finish and task.date_deadline:
                # Calendar-day diff in the user's timezone — the same
                # frame finish_variance_state serializes in.
                done_day = fields.Datetime.context_timestamp(
                    task, task.actual_finish
                ).date()
                stop_day = fields.Datetime.context_timestamp(
                    task, task.date_deadline
                ).date()
                days = (done_day - stop_day).days
                task.schedule_variance_days = days
                task.schedule_variance_state = (
                    "late" if days > 0 else "early" if days < 0 else "on_time"
                )
            else:
                task.schedule_variance_days = False
                task.schedule_variance_state = False

    @api.constrains("date_actual_start", "date_actual_end")
    def _check_actual_dates(self):
        for task in self:
            if (
                task.date_actual_start
                and task.date_actual_end
                and task.date_actual_end < task.date_actual_start
            ):
                raise ValidationError(_(
                    "Actual End cannot be earlier than Actual Start."
                ))

    # ---- Planner payload ---------------------------------------------------

    def _planner_actual_fields(self):
        """Actual-tracking keys merged into planner task rows by
        ``project.project.get_planner_data``."""
        self.ensure_one()
        return {
            "actual_start": _serialize_planner_day(self, self.date_actual_start),
            "dt_actual_start": _serialize_planner_dt(self, self.date_actual_start),
            "actual_end": _serialize_planner_day(self, self.actual_finish),
            "dt_actual_end": _serialize_planner_dt(self, self.actual_finish),
            "actual_duration": self.actual_duration or 0.0,
            "actual_status": self.actual_status,
            "schedule_variance_days": (
                self.schedule_variance_days
                if self.schedule_variance_days is not False else False
            ),
            "schedule_variance_state": self.schedule_variance_state or False,
        }

    def get_planner_detail(self):
        """Actual block for the Quick Inspector — same keys as the row
        payload so the inspector can show plan-vs-actual side by side."""
        res = super().get_planner_detail()
        res["actual"] = {
            "date_start": _serialize_planner_day(self, self.date_actual_start),
            "dt_start": _serialize_planner_dt(self, self.date_actual_start),
            "date_end": _serialize_planner_day(self, self.actual_finish),
            "dt_end": _serialize_planner_dt(self, self.actual_finish),
            "duration": self.actual_duration or 0.0,
            "status": self.actual_status,
            "variance_days": (
                self.schedule_variance_days
                if self.schedule_variance_days is not False else False
            ),
            "variance_state": self.schedule_variance_state or False,
        }
        return res
