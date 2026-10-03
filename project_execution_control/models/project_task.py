# -*- coding: utf-8 -*-

from collections import defaultdict

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

    # ---- Material risk (BRD §6/§7) ------------------------------------------
    # Reverse link to the requirement lines that live in
    # project_resource_planning — one row per (project, task, product).
    material_plan_line_ids = fields.One2many(
        "project.material.plan", "task_id", string="Material Plan Lines",
        readonly=True,
    )
    material_risk = fields.Selection(
        [
            ("no_risk", "No Material Risk"),
            ("partial", "Partial Availability"),
            ("delayed", "Material Delay"),
            ("critical", "Critical Material Delay"),
        ],
        string="Material Risk", compute="_compute_material_values",
        search="_search_material_risk",
    )
    material_delay_days = fields.Float(
        string="Material Delay (Days)", compute="_compute_material_values",
        digits=(16, 1),
    )
    # What the task itself is expected to slip by — today the same number
    # as the worst line delay; kept as a separate KPI because later phases
    # may cap it against work already performed.
    material_expected_delay_days = fields.Float(
        string="Expected Task Delay (Days)", compute="_compute_material_values",
        digits=(16, 1),
    )
    material_downstream_count = fields.Integer(
        string="Downstream Tasks Affected", compute="_compute_material_values",
    )
    material_downstream_impact_days = fields.Float(
        string="Worst Downstream Impact (Days)",
        compute="_compute_material_values", digits=(16, 1),
    )
    material_project_impact_days = fields.Float(
        string="Project Finish Impact (Days)",
        compute="_compute_material_values", digits=(16, 1),
    )
    material_shortage_quantity = fields.Float(
        string="Material Shortage", compute="_compute_material_values",
        digits="Product Unit of Measure",
    )
    material_risk_detail = fields.Char(
        string="Material Risk Detail", compute="_compute_material_values",
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

    # ---- Material risk computation -----------------------------------------

    @api.depends(
        "project_id",
        "material_plan_line_ids.material_state",
        "material_plan_line_ids.material_delay_days",
        "material_plan_line_ids.shortage_quantity",
    )
    def _compute_material_values(self):
        """Batch per project: line aggregation is cheap; the propagation
        runs one perturbed forward pass per delayed task over the shared
        dependency graph — the CPM itself is never duplicated."""
        by_project = defaultdict(lambda: self.env["project.task"])
        for task in self:
            if task.project_id:
                by_project[task.project_id.id] |= task
            else:
                task.material_risk = "no_risk"
                task.material_delay_days = 0.0
                task.material_expected_delay_days = 0.0
                task.material_downstream_count = 0
                task.material_downstream_impact_days = 0.0
                task.material_project_impact_days = 0.0
                task.material_shortage_quantity = 0.0
                task.material_risk_detail = False
        projects = self.env["project.project"].browse(list(by_project))
        for project in projects:
            tasks = by_project[project.id]
            delayed_tasks = tasks.filtered(
                lambda t: max(
                    t.material_plan_line_ids.mapped("material_delay_days"),
                    default=0.0,
                ) > 0.000001
            )
            impacts = {}
            if delayed_tasks:
                graph = project._get_task_dependency_graph()
                schedule = project._calculate_task_schedule(graph)
                hpd = _planner_hours_per_day(project)
                for task in delayed_tasks:
                    delay = max(
                        task.material_plan_line_ids.mapped("material_delay_days"))
                    deltas, project_delta = project._propagate_start_delay(
                        graph, schedule, task.id, delay * hpd,
                    )
                    impacts[task.id] = (
                        len(deltas),
                        (max(deltas.values()) / hpd) if deltas else 0.0,
                        max(0.0, project_delta) / hpd,
                    )
            for task in tasks:
                lines = task.material_plan_line_ids
                states = set(lines.mapped("material_state"))
                delay = max(lines.mapped("material_delay_days"), default=0.0)
                shortage = sum(lines.mapped("shortage_quantity"))
                downstream, downstream_days, project_days = impacts.get(
                    task.id, (0, 0.0, 0.0))
                if not lines:
                    risk = "no_risk"
                elif project_days > 0.000001:
                    risk = "critical"
                elif states & {"delayed", "unknown"}:
                    risk = "delayed"
                elif "partial" in states:
                    risk = "partial"
                else:
                    risk = "no_risk"
                task.material_risk = risk
                task.material_delay_days = delay
                task.material_expected_delay_days = delay
                task.material_downstream_count = downstream
                task.material_downstream_impact_days = downstream_days
                task.material_project_impact_days = project_days
                task.material_shortage_quantity = shortage
                risky = lines.filtered(
                    lambda l: l.material_state in ("delayed", "partial", "unknown"))
                task.material_risk_detail = "; ".join(
                    "%s: %s" % (
                        l.product_id.display_name,
                        dict(l._fields["material_state"].selection).get(
                            l.material_state, l.material_state),
                    ) for l in risky
                ) or False

    def _search_material_risk(self, operator, value):
        """Domain support on the non-stored risk field — computed per
        project once, then mapped to ids. Tasks without material lines
        live on the ``no_risk`` side of every comparison."""
        wanted = {value} if isinstance(value, str) else set(value or [])
        all_tasks = self.with_context(active_test=False).search([])
        all_tasks.mapped("material_risk")  # one batched compute
        matching = all_tasks.filtered(lambda t: t.material_risk in wanted)
        if operator in ("!=", "not in"):
            matching = all_tasks - matching
        return [("id", "in", matching.ids)]

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

    def _planner_material_fields(self):
        """Material-risk keys merged into planner task rows by
        ``project.project.get_planner_data`` (same post-processing point
        as the actual block — never lost to sibling overrides)."""
        self.ensure_one()
        return {
            "material_risk": self.material_risk or "no_risk",
            "material_delay_days": self.material_delay_days or 0.0,
            "material_project_impact_days": (
                self.material_project_impact_days or 0.0),
            "material_downstream_count": self.material_downstream_count or 0,
            "material_shortage_quantity": (
                self.material_shortage_quantity or 0.0),
            "material_risk_detail": self.material_risk_detail or False,
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
        # Material block (Phase 2): the inspector gets the same numbers
        # as the row payload plus the per-line read-out.
        res["material"] = dict(
            self._planner_material_fields(),
            lines=[{
                "id": line.id,
                "product": line.product_id.display_name,
                "planned_quantity": line.planned_quantity,
                "uom": line.uom_id.name,
                "required_date": _serialize_planner_day(
                    line, line.required_date),
                "available_quantity": line.available_quantity,
                "shortage_quantity": line.shortage_quantity,
                "expected_availability": _serialize_planner_dt(
                    line, line.expected_availability_date),
                "material_delay_days": line.material_delay_days,
                "material_state": line.material_state,
            } for line in self.material_plan_line_ids],
        )
        return res
