# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

from pytz import UTC, timezone

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


def _serialize_planner_day(record, value):
    """Serialize a date/datetime field to a ``YYYY-MM-DD`` day in user tz."""
    if not value:
        return False
    if isinstance(value, datetime):
        return fields.Datetime.context_timestamp(record, value).date().isoformat()
    return value.isoformat()


def _serialize_planner_dt(record, value):
    """Serialize a datetime to ``YYYY-MM-DD HH:MM`` in user tz — used by the
    Resource Planning timeline where hour precision matters."""
    if not value:
        return False
    return fields.Datetime.context_timestamp(record, value).strftime(
        "%Y-%m-%d %H:%M"
    )


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
        """Return the projects selectable in the Planner Workspace picker
        plus the dedicated search view id (resolved server-side so the
        client never needs ir.ui.view read access)."""
        return {
            "projects": [
                {"id": project.id, "name": project.display_name}
                for project in self.search([], order="name")
            ],
            "search_view_id": self.env.ref(
                "project_critical_path.project_task_planner_search", raise_if_not_found=False
            ).id or False,
        }

    def get_planner_data(self, baseline_id=None, domain=None):
        """Return the project's tasks in WBS order for the Planner Workspace.

        The list is already flattened in display order so the WBS panel and the
        Gantt timeline share the exact same row sequence.

        ``baseline_id`` optionally overrides the comparison baseline used for
        the ghost/variance layer so the Gantt can show a historical baseline
        against the current plan without touching any baseline record.

        ``domain`` is the standard search-view domain coming from the
        planner's search bar — matching tasks are kept together with their
        WBS ancestors so the hierarchy stays readable (BRD-XX).
        """
        self.ensure_one()
        all_tasks = self.env["project.task"].with_context(active_test=False).search(
            [("project_id", "=", self.id)]
        )
        tasks = all_tasks
        if domain:
            matched = self.env["project.task"].with_context(active_test=False).search(
                [("project_id", "=", self.id)] + list(domain)
            )
            keep = set(matched.ids)
            queue = [task.parent_id for task in matched if task.parent_id]
            while queue:
                parent = queue.pop()
                if parent and parent.project_id == self and parent.id not in keep:
                    keep.add(parent.id)
                    queue.append(parent.parent_id)
            tasks = all_tasks.filtered(lambda task: task.id in keep)
        ordered = tasks.sorted(key=lambda task: (task.wbs_sort_key or "", task.sequence, task.id))
        baseline = self.delay_impact_baseline_id
        if baseline_id:
            override = self.env["project.critical.path.baseline"].browse(baseline_id).exists()
            if override and override.project_id == self:
                baseline = override
        baseline_by_task = {
            line.task_id.id: line for line in baseline.line_ids if line.task_id
        } if baseline else {}
        # Per-edge relationship type/lag attributes (BRD Dependency Lag) —
        # reconciled against the M2M so the map covers every edge.
        dependency_rows = self._ensure_dependency_records()
        # Compact per-task resource summary for the row badges.
        requirements = self.env["project.task.resource.requirement"].search(
            [("project_id", "=", self.id)]
        )
        resources_by_task = {}
        for requirement in requirements:
            entry = resources_by_task.setdefault(
                requirement.task_id.id,
                {"human": 0, "equipment": 0, "open": 0, "names": []},
            )
            if requirement.assignment_status != "assigned":
                entry["open"] += 1
            for assignment in requirement.assignment_ids:
                key = "human" if requirement.role_id.category == "human" else "equipment"
                entry[key] += 1
                entry["names"].append(
                    (assignment.employee_id or assignment.equipment_id).display_name
                )
        # Standard Filters & Group By (BRD): option lists come from the FULL
        # project task set — they stay available even while a filter hides
        # the tasks that produced them.
        stages = self.type_ids
        if not stages:
            stages = self.env["project.task.type"].search(
                [("project_ids", "in", self.id)]
            )
        if not stages:
            stages = self.env["project.task.type"].search([])
        meta = {
            "users": [
                {"id": user.id, "name": user.name}
                for user in all_tasks.mapped("user_ids")
            ],
            "roles": [
                {"id": role.id, "name": role.name, "category": role.category}
                for role in requirements.mapped("role_id")
            ],
            "stages": [{"id": stage.id, "name": stage.name} for stage in stages],
            "parents": [
                {"id": task.id, "name": task.name, "wbs_code": task.wbs_code or ""}
                for task in all_tasks.filtered(lambda task: not task.parent_id).sorted(
                    key=lambda task: (task.wbs_sort_key or "", task.sequence, task.id)
                )
            ],
        }
        return {
            "project": {"id": self.id, "name": self.display_name},
            "meta": meta,
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
                    # Localized datetimes — the day-scale timeline positions
                    # and drags bars at hour precision.
                    "dt_start": _serialize_planner_dt(self, task.date_assign),
                    "dt_stop": _serialize_planner_dt(self, task.date_deadline),
                    "progress": task.progress or 0.0,
                    "allocated_hours": task.allocated_hours or 0.0,
                    "effective_hours": getattr(task, "effective_hours", 0.0) or 0.0,
                    "is_critical": bool(task.is_critical),
                    "critical_slack": task.critical_slack or 0.0,
                    # Done is the Odoo task state, never a progress threshold
                    "is_done": task.state == "1_done",
                    # Group By keys (BRD Standard Filters) — display values
                    # only; filtering itself runs on real fields via domain.
                    "user_ids": task.user_ids.ids,
                    "user_names": task.user_ids.mapped("name"),
                    "stage_name": task.stage_id.name or "",
                    "role_names": sorted(set(
                        task.resource_requirement_ids.mapped("role_id.name")
                    )),
                    # Requirement categories — needed (not only assigned)
                    # resource types, so the Resource Type group-by sees
                    # open requirements too.
                    "role_categories": sorted(set(
                        task.resource_requirement_ids.mapped("role_id.category")
                    )),
                    "depend_on_ids": task.depend_on_ids.ids,
                    "dependencies": [
                        dependency_rows[(task.id, dependency.id)]._serialize()
                        for dependency in task.depend_on_ids
                        if (task.id, dependency.id) in dependency_rows
                    ],
                    "baseline_name": baseline.name if baseline_by_task.get(task.id) else False,
                    "baseline_start": (
                        _serialize_planner_day(self, baseline_by_task[task.id].planned_date_begin)
                        if baseline_by_task.get(task.id) else False
                    ),
                    "baseline_stop": (
                        _serialize_planner_day(self, baseline_by_task[task.id].planned_date_end)
                        if baseline_by_task.get(task.id) else False
                    ),
                    "resources": resources_by_task.get(
                        task.id, {"human": 0, "equipment": 0, "open": 0, "names": []},
                    ),
                }
                for task in ordered
            ],
        }

    def get_planner_baseline_history(self):
        """Read-only list of this project's baseline versions, newest first.

        Only stored snapshot/history fields are serialized — nothing is
        recalculated, so opening the list stays cheap.
        """
        self.ensure_one()
        baselines = self.env["project.critical.path.baseline"].search(
            [("project_id", "=", self.id)]
        )
        return [
            {
                "id": baseline.id,
                "name": baseline.name,
                # Version is always the "v1.X" prefix; the label is the
                # optional user-chosen baseline title appended after it.
                "version": "v1.%d" % baseline.revision_number,
                "label": baseline.name.partition(" - ")[2] or False,
                "created_on": fields.Datetime.to_string(baseline.created_on),
                "project_duration": baseline.project_duration or 0.0,
                "previous_id": baseline.previous_baseline_id.id or False,
                "previous_name": baseline.previous_baseline_id.name or False,
                # Version-only reference for the comparison line — titles
                # stay out of "x vs v1.Y" (BRD).
                "previous_version": (
                    "v1.%d" % baseline.previous_baseline_id.revision_number
                    if baseline.previous_baseline_id else False
                ),
                "duration_variance": baseline.history_project_duration_variance or 0.0,
                "planned_cost": baseline.planned_resource_cost or 0.0,
                "cost_variance": baseline.history_planned_cost_variance or 0.0,
                "currency_symbol": baseline.currency_id.symbol or "",
                "is_initial": not baseline.previous_baseline_id,
            }
            for baseline in baselines
        ]

    def get_planner_baseline_summary(self, baseline_id):
        """Read-only change summary of one baseline vs its previous version.

        Task-level changes are derived by comparing the frozen snapshot lines
        of the two consecutive baselines — no baseline or critical-path data
        is recomputed or modified.
        """
        self.ensure_one()
        baseline = self.env["project.critical.path.baseline"].browse(baseline_id).exists()
        if not baseline or baseline.project_id != self:
            return False
        previous = baseline.previous_baseline_id
        current_lines = {line.task_id.id: line for line in baseline.line_ids if line.task_id}
        previous_lines = {
            line.task_id.id: line for line in previous.line_ids if line.task_id
        } if previous else {}
        changes = []
        cp_changes = 0
        for task_id, line in current_lines.items():
            if not previous:
                break  # initial baseline has nothing to compare against
            prev = previous_lines.get(task_id)
            delta = round(
                line.allocated_hours - (prev.allocated_hours if prev else 0.0), 2,
            )
            entered = bool(line.is_critical) and not (prev and prev.is_critical)
            left = bool(prev and prev.is_critical) and not line.is_critical
            dates_changed = bool(prev) and (
                line.planned_date_begin != prev.planned_date_begin
                or line.planned_date_end != prev.planned_date_end
            )
            cost_delta = round(
                (line.planned_cost or 0.0) - (prev.planned_cost if prev else 0.0), 2,
            )
            if not (delta or entered or left or dates_changed or cost_delta):
                continue
            changes.append({
                "task_id": task_id,
                "task_name": line.task_name,
                "delta_hours": delta,
                "old_hours": prev.allocated_hours if prev else False,
                "new_hours": line.allocated_hours,
                "delta_cost": cost_delta,
                "old_cost": prev.planned_cost if prev else False,
                "new_cost": line.planned_cost or 0.0,
                # Strictly longer than the frozen previous snapshot — drives
                # the light-red row highlight in Baseline History.
                "duration_increased": prev is not None and delta > 0,
                "entered_cp": entered,
                "left_cp": left,
                "new_task": prev is None,
                "removed_task": False,
                "dates_changed": dates_changed,
            })
            cp_changes += int(entered) + int(left)
        if previous:
            for task_id in sorted(set(previous_lines) - set(current_lines)):
                line = previous_lines[task_id]
                changes.append({
                    "task_id": task_id,
                    "task_name": line.task_name,
                    "delta_hours": False,
                    "old_hours": line.allocated_hours,
                    "new_hours": False,
                    "delta_cost": False,
                    "old_cost": line.planned_cost or 0.0,
                    "new_cost": False,
                    "duration_increased": False,
                    "entered_cp": False,
                    "left_cp": False,
                    "new_task": False,
                    "removed_task": True,
                    "dates_changed": False,
                })
        changes.sort(key=lambda item: (-abs(item["delta_hours"] or 0.0), item["task_name"]))
        return {
            "id": baseline.id,
            "name": baseline.name,
            "version": "v1.%d" % baseline.revision_number,
            "label": baseline.name.partition(" - ")[2] or False,
            "created_on": fields.Datetime.to_string(baseline.created_on),
            "project_duration": baseline.project_duration or 0.0,
            "critical_path_duration": baseline.critical_path_duration or 0.0,
            "previous_id": previous.id or False,
            "previous_name": previous.name or False,
            "previous_version": "v1.%d" % previous.revision_number if previous else False,
            "previous_duration": previous.project_duration if previous else False,
            "duration_variance": baseline.history_project_duration_variance or 0.0,
            "cp_duration_variance": baseline.history_critical_path_duration_variance or 0.0,
            "planned_cost": baseline.planned_resource_cost or 0.0,
            "previous_cost": previous.planned_resource_cost if previous else False,
            "cost_variance": baseline.history_planned_cost_variance or 0.0,
            "currency_symbol": baseline.currency_id.symbol or "",
            "is_initial": not previous,
            "task_count": len(baseline.line_ids),
            "tasks_changed": len(changes),
            "cp_changes": cp_changes,
            "changes": changes,
        }

    def planner_get_resource_board(self, window_start=None, window_end=None):
        """All eligible resources with their bookings inside the window.

        Personnel = active employees carrying at least one resource role,
        equipment = all active equipment. Occupancy is work-hours booked in
        the window over work-hours available on the resource (or company)
        calendar. Booking windows cross project boundaries on purpose —
        capacity planning cares about the resource, not the project.
        """
        self.ensure_one()
        win_start = _local_dt_to_utc(self, window_start, None, 0)
        win_end = _local_dt_to_utc(self, window_end, None, 23)
        if not (win_start and win_end):
            return {"resources": []}
        employees = self.env["hr.employee"].search(
            [("active", "=", True), ("resource_role_ids", "!=", False)], order="name")
        equipment = self.env["maintenance.equipment"].search(
            [("active", "=", True)], order="name")
        bookings = self.env["project.task.resource.assignment"].search([
            ("date_start", "<", win_end), ("date_end", ">", win_start),
        ], order="date_start, id")
        company_cal = self.env.company.resource_calendar_id
        task_states = dict(
            self.env["project.task"].fields_get(["state"], ["selection"])["state"]["selection"]
        )

        by_res = {"employee_id": {}, "equipment_id": {}}
        for booking in bookings:
            resource = booking.employee_id or booking.equipment_id
            if resource:
                field = "employee_id" if booking.employee_id else "equipment_id"
                by_res[field].setdefault(resource.id, []).append(booking)

        def entry(resource, field):
            res_bookings = by_res[field].get(resource.id, [])
            calendar = getattr(resource, "resource_calendar_id", False) or company_cal
            booked = 0.0
            for booking in res_bookings:
                start = max(booking.date_start, win_start)
                end = min(booking.date_end, win_end)
                booked += (calendar.get_work_hours_count(start, end, compute_leaves=True)
                           if calendar else (end - start).total_seconds() / 3600.0)
            available = (calendar.get_work_hours_count(win_start, win_end, compute_leaves=True)
                         if calendar else (win_end - win_start).total_seconds() / 3600.0)
            return {
                "key": ("e" if field == "employee_id" else "q") + str(resource.id),
                "employee_id": resource.id if field == "employee_id" else False,
                "equipment_id": resource.id if field == "equipment_id" else False,
                "category": "human" if field == "employee_id" else "equipment",
                "name": resource.display_name,
                "priority": int(resource.priority or 0) if field == "employee_id" else 0,
                "booked_hours": round(booked, 2),
                "available_hours": round(available, 2),
                "occupancy": round(booked / available * 100) if available else (100 if booked else 0),
                "schedule": [{
                    "id": booking.id,
                    "task_name": booking.task_id.display_name,
                    "task_state": task_states.get(booking.task_id.state) or "",
                    "project_name": booking.project_id.display_name,
                    "planned_hours": booking.planned_hours or 0.0,
                    "date_start": _serialize_planner_day(self, booking.date_start),
                    "date_end": _serialize_planner_day(self, booking.date_end),
                    "dt_start": _serialize_planner_dt(self, booking.date_start),
                    "dt_end": _serialize_planner_dt(self, booking.date_end),
                } for booking in res_bookings],
            }

        personnel = sorted(
            (entry(emp, "employee_id") for emp in employees),
            key=lambda e: (-e["priority"], e["name"].lower()),
        )
        return {"resources": personnel + [entry(eq, "equipment_id") for eq in equipment]}


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
        baseline = project.delay_impact_baseline_id if project else self.env["project.critical.path.baseline"]
        line = baseline.line_ids.filtered(lambda item: item.task_id == self)[:1] if baseline else False
        baseline_start = _serialize_planner_day(line, line.planned_date_begin) if line else False
        baseline_stop = _serialize_planner_day(line, line.planned_date_end) if line else False
        dependency_rows = project._ensure_dependency_records() if project else {}
        return {
            "task": {
                "id": self.id,
                "name": self.name or "",
                "wbs_code": self.wbs_code or "",
                "is_critical": bool(self.is_critical),
                "critical_slack": self.critical_slack or 0.0,
                "date_start": _serialize_planner_day(self, self.date_assign),
                "date_stop": _serialize_planner_day(self, self.date_deadline),
                # Localized datetimes — the Inspector time inputs and the
                # day-scale timeline keep hour precision.
                "dt_start": _serialize_planner_dt(self, self.date_assign),
                "dt_stop": _serialize_planner_dt(self, self.date_deadline),
                "allocated_hours": self.allocated_hours or 0.0,
                "hours_per_day": _planner_hours_per_day(self),
                "effective_hours": getattr(self, "effective_hours", 0.0) or 0.0,
                # progress is stored as a 0..1 ratio; the inspector shows 0..100
                "progress": round((self.progress or 0.0) * 100, 1),
                "stage_id": self.stage_id.id or False,
                "user_ids": self.user_ids.ids,
                "depend_on_ids": self.depend_on_ids.ids,
                "dependent_ids": self.dependent_ids.ids,
                "dependencies": [
                    dependency_rows[(self.id, dependency.id)]._serialize()
                    for dependency in self.depend_on_ids
                    if (self.id, dependency.id) in dependency_rows
                ],
            },
            "baseline": {
                "name": baseline.name if baseline else False,
                "has_line": bool(line),
                "date_start": baseline_start,
                "date_stop": baseline_stop,
                # inclusive day-based duration, same convention as the
                # inspector duration field
                "duration_days": (
                    (datetime.strptime(baseline_stop, "%Y-%m-%d")
                     - datetime.strptime(baseline_start, "%Y-%m-%d")).days + 1
                    if baseline_start and baseline_stop else False
                ),
                "allocated_hours": line.allocated_hours if line else False,
                "is_critical": line.is_critical if line else None,
            },
            "impact": {
                "delay_baseline_duration": self.delay_baseline_duration or 0.0,
                "delay_duration_variance": self.delay_duration_variance or 0.0,
                "delay_project_impact": self.delay_project_impact or 0.0,
                "delay_impact_status": self.delay_impact_status or False,
                "delay_impact_chain": self.delay_impact_chain or False,
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
            vals["date_assign"] = _local_day_to_utc(self, values["date_start"], self.date_assign, 9)
        if "date_stop" in values:
            vals["date_deadline"] = _local_day_to_utc(self, values["date_stop"], self.date_deadline, 18)
        # Hour-precision variant used by day-scale timeline drags —
        # "YYYY-MM-DD HH:MM" local strings.
        if "dt_start" in values:
            vals["date_assign"] = _local_dt_to_utc(self, values["dt_start"], self.date_assign, 9)
        if "dt_stop" in values:
            vals["date_deadline"] = _local_dt_to_utc(self, values["dt_stop"], self.date_deadline, 18)
        # Planned hours for dt writes: a same-day bar is its real hour span,
        # a multi-day bar keeps the day-span * hours-per-day convention.
        if values.get("dt_start") and values.get("dt_stop") and "allocated_hours" not in values:
            dt_start = datetime.strptime(values["dt_start"].strip()[:16], "%Y-%m-%d %H:%M")
            dt_stop = datetime.strptime(values["dt_stop"].strip()[:16], "%Y-%m-%d %H:%M")
            if dt_start.date() == dt_stop.date():
                vals["allocated_hours"] = max(
                    (dt_stop - dt_start).total_seconds() / 3600.0, 0.0
                )
            else:
                span_days = (dt_stop.date() - dt_start.date()).days + 1
                vals["allocated_hours"] = max(
                    span_days, 0.0
                ) * _planner_hours_per_day(self)
        # Keep allocated_hours (the duration used by critical-path, delay-impact
        # and baseline comparisons) in sync when the inspector duration changes.
        # ``duration_days`` is inclusive — a bar covering N day cells is an
        # N-day task, matching how the Gantt renders it.
        days = values.get("duration_days")
        if values.get("date_start") and values.get("date_stop") and days not in (None, False):
            stored_start = _serialize_planner_day(self, self.date_assign)
            stored_stop = _serialize_planner_day(self, self.date_deadline)
            stored_days = (
                (datetime.strptime(stored_stop, "%Y-%m-%d")
                 - datetime.strptime(stored_start, "%Y-%m-%d")).days + 1
                if stored_start and stored_stop else None
            )
            if float(days) != stored_days:
                vals["allocated_hours"] = max(float(days), 0.0) * _planner_hours_per_day(self)
        # The inspector edits duration in hours: an explicit allocated_hours
        # is authoritative and wins over the day-span derivation above, so
        # fractional-day durations (e.g. 20 h over a 3-day window) survive.
        if "allocated_hours" in values:
            vals["allocated_hours"] = max(float(values["allocated_hours"] or 0.0), 0.0)
            # BRD Auto-Scheduling: a duration-only edit (no explicit finish
            # in the same write) stretches the plan from the finish side —
            # the write hook then reschedules violating successors.
            if (
                self.date_assign and self.date_deadline
                and "date_stop" not in values and "dt_stop" not in values
            ):
                delta_hours = vals["allocated_hours"] - (self.allocated_hours or 0.0)
                if delta_hours:
                    vals["date_deadline"] = self.date_deadline + timedelta(
                        hours=delta_hours
                    )
        if "progress" in values:
            vals["progress"] = min(max(values["progress"] or 0.0, 0.0), 100.0) / 100.0
        if "stage_id" in values:
            vals["stage_id"] = values["stage_id"] or False
        if "user_ids" in values:
            # Odoo clears date_assign (the native "assigning date" the
            # Planner reuses as planned start) inside write() whenever the
            # assignee set ends up empty. Apply the assignee change first so
            # the date fields written afterwards survive the same save —
            # and restore the planned start when it was cleared without an
            # explicit start in this update (e.g. a stop-only save).
            preserved_start = self.date_assign
            self.write({"user_ids": [Command.set(values["user_ids"] or [])]})
            if preserved_start and not self.date_assign and "date_assign" not in vals:
                vals["date_assign"] = preserved_start
        if "depend_on_ids" in values:
            vals["depend_on_ids"] = [Command.set(values["depend_on_ids"] or [])]
        if "dependent_ids" in values:
            vals["dependent_ids"] = [Command.set(values["dependent_ids"] or [])]
        self.write(vals)
        return True

    def update_planner_dependency(
        self, depends_on_id, relationship_type="fs", lag=0.0, lag_unit="hours",
    ):
        """Write the relationship type and lag of the edge depends_on_id → self.

        Called from the Planner dependency-arrow editor. The M2M edge must
        already exist — the attribute row is created lazily if the edge was
        added since the last reconciliation.
        """
        self.ensure_one()
        if depends_on_id not in self.depend_on_ids.ids:
            raise UserError(_("The dependency no longer exists."))
        if relationship_type not in ("fs", "ss", "ff", "sf"):
            relationship_type = "fs"
        if lag_unit not in ("hours", "days"):
            lag_unit = "hours"
        Dependency = self.env["project.task.dependency"]
        row = Dependency.search(
            [
                ("task_id", "=", self.id),
                ("depends_on_id", "=", depends_on_id),
            ],
            limit=1,
        )
        if not row:
            row = Dependency.create(
                {"task_id": self.id, "depends_on_id": depends_on_id}
            )
        row.write(
            {
                "relationship_type": relationship_type,
                "lag": float(lag or 0.0),
                "lag_unit": lag_unit,
            }
        )
        # Edge attributes feed the CPM and the auto-shift bounds — a plain
        # task write is not involved, so the scheduling check and the
        # recalculation are triggered explicitly.
        if self.project_id:
            self.project_id._schedule_dependents(self)
            self.project_id._recalculate_critical_paths()
        return True

    # ---- Planner Resources (BRD-21) ---------------------------------------
    # Thin serialization/mutation over the existing resource models
    # (project.task.resource.requirement / .assignment / project.resource.planner).

    def get_planner_resources(self):
        """Requirements, assignments and role options for the Resources
        section of the Quick Inspector."""
        self.ensure_one()
        Requirement = self.env["project.task.resource.requirement"]
        roles = self.env["project.resource.role"].search([("active", "=", True)])
        templates = self.project_id.resource_rate_template_ids
        currency = (
            self.project_id.resource_currency_id
            or templates[:1].currency_id
            or self.env.company.currency_id
        )
        return {
            "requirements": [
                {
                    "id": requirement.id,
                    "role_id": requirement.role_id.id,
                    "role_name": requirement.role_id.name or "",
                    "category": requirement.role_id.category,
                    "level": int(requirement.level or 0),
                    "quantity": requirement.quantity or 0.0,
                    "planned_hours": requirement.planned_hours or 0.0,
                    "hourly_rate": requirement.hourly_rate or 0.0,
                    "planned_cost": requirement.planned_cost or 0.0,
                    "date_start": _serialize_planner_day(self, requirement.date_start),
                    "date_end": _serialize_planner_day(self, requirement.date_end),
                    "description": requirement.description or "",
                    "assigned_quantity": requirement.assigned_quantity,
                    "assigned_hours": requirement.assigned_hours,
                    "status": requirement.assignment_status,
                    "assignments": [
                        {
                            "id": assignment.id,
                            "employee_id": assignment.employee_id.id or False,
                            "equipment_id": assignment.equipment_id.id or False,
                            "name": (
                                assignment.employee_id or assignment.equipment_id
                            ).display_name,
                            "planned_hours": assignment.planned_hours or 0.0,
                        }
                        for assignment in requirement.assignment_ids
                    ],
                }
                for requirement in Requirement.search([("task_id", "=", self.id)])
            ],
            "roles": [
                {
                    "id": role.id,
                    "name": role.name,
                    "category": role.category,
                    "priority": int(role.priority or 0),
                }
                for role in roles
            ],
            # The project's selected rate templates are shipped so the form
            # can preview the role's rate and planned cost before saving;
            # the authoritative snapshot still happens server-side on write.
            "rate_template": {
                "currency_symbol": currency.symbol or "",
            } if templates else None,
            "rates": [
                {
                    "role_id": template.role_id.id or None,
                    "hourly_rate": template.hourly_rate,
                }
                for template in templates
            ],
            "task_dates": {
                "date_start": _serialize_planner_day(self, self.date_assign),
                "date_stop": _serialize_planner_day(self, self.date_deadline),
            },
        }

    def _get_planner_requirement(self, requirement_id):
        requirement = self.env["project.task.resource.requirement"].browse(
            requirement_id
        ).exists()
        if not requirement or requirement.task_id != self:
            raise UserError(_("This resource requirement does not belong to the task."))
        return requirement

    def planner_save_requirement(self, values):
        """Create or update a requirement from the Planner resource section."""
        self.ensure_one()
        Requirement = self.env["project.task.resource.requirement"]
        vals = {}
        if "role_id" in values:
            vals["role_id"] = values["role_id"] or False
        if "quantity" in values:
            vals["quantity"] = values["quantity"] or 1.0
        if "planned_hours" in values:
            vals["planned_hours"] = values["planned_hours"] or 0.0
        if "description" in values:
            vals["description"] = values["description"]
        if "date_start" in values:
            vals["date_start"] = (
                _local_day_to_utc(self, values["date_start"], None, 9)
                if values["date_start"] else False
            )
        if "date_end" in values:
            vals["date_end"] = (
                _local_day_to_utc(self, values["date_end"], None, 18)
                if values["date_end"] else False
            )
        req_id = values.get("id")
        if req_id:
            requirement = self._get_planner_requirement(req_id)
            requirement.write(vals)
            return True
        vals["task_id"] = self.id
        # Empty dates fall back to the task dates via the model's create hook.
        for key in ("date_start", "date_end"):
            if key in vals and not vals[key]:
                vals.pop(key)
        Requirement.create(vals)
        return True

    def planner_delete_requirement(self, requirement_id):
        self.ensure_one()
        self._get_planner_requirement(requirement_id).unlink()
        return True

    def planner_get_assignment_options(
        self, requirement_id, window_start=None, window_end=None,
    ):
        """Eligible employees/equipment with availability for one requirement.

        Reuses the existing transient Team Planner so availability, booked
        hours and conflict summaries come from the same logic as the task
        form's resource planner. ``window_start``/``window_end`` are optional
        ``YYYY-MM-DD`` days overriding the default requirement±2-day window
        (the timeline requests its visible range on scale/navigation changes).
        """
        self.ensure_one()
        requirement = self._get_planner_requirement(requirement_id)
        planner = self.env["project.resource.planner"].create_for_requirement(requirement)
        req_start, req_end = requirement.date_start, requirement.date_end
        if window_start:
            window_start = _local_dt_to_utc(self, window_start, None, 0)
        elif req_start:
            window_start = req_start - timedelta(days=2)
        if window_end:
            window_end = _local_dt_to_utc(self, window_end, None, 23)
        elif req_end:
            window_end = req_end + timedelta(days=2)
        # Every candidate's existing assignments inside the timeline window,
        # fetched in one query so browsing candidates costs no extra RPC.
        schedules = {}
        if window_start and window_end:
            res_field = (
                "employee_id"
                if requirement.role_id.category == "human"
                else "equipment_id"
            )
            bookings = self.env["project.task.resource.assignment"].search([
                ("resource_category", "=", requirement.role_id.category),
                ("date_start", "<=", window_end),
                ("date_end", ">=", window_start),
            ], order="date_start, id")
            for booking in bookings:
                schedules.setdefault(booking[res_field].id, []).append({
                    "id": booking.id,
                    "requirement_id": booking.requirement_id.id,
                    "mine": booking.requirement_id == requirement,
                    "task_name": booking.task_id.display_name,
                    "planned_hours": booking.planned_hours or 0.0,
                    "date_start": _serialize_planner_day(self, booking.date_start),
                    "date_end": _serialize_planner_day(self, booking.date_end),
                    "dt_start": _serialize_planner_dt(self, booking.date_start),
                    "dt_end": _serialize_planner_dt(self, booking.date_end),
                    "overlaps": bool(
                        req_start and req_end
                        and booking.date_start <= req_end
                        and booking.date_end >= req_start
                    ),
                })
        options = [
            {
                "employee_id": line.employee_id.id or False,
                "equipment_id": line.equipment_id.id or False,
                "priority": line.priority or 0,
                "name": line.resource_name,
                "availability": line.availability_status,
                "booked_hours": line.booked_hours,
                "available_hours": line.available_hours,
                "booking_summary": line.booking_summary or "",
                "schedule": schedules.get(
                    (line.employee_id or line.equipment_id).id, []
                ),
            }
            for line in planner.line_ids
        ]
        planner.unlink()
        options.sort(key=lambda option: -(option["priority"] or 0))
        return {
            "options": options,
            "window": {
                "start": _serialize_planner_day(self, window_start),
                "end": _serialize_planner_day(self, window_end),
            },
            "required": {
                "start": _serialize_planner_day(self, req_start),
                "end": _serialize_planner_day(self, req_end),
                "start_dt": _serialize_planner_dt(self, req_start),
                "end_dt": _serialize_planner_dt(self, req_end),
            },
        }

    def planner_assign_resource(
        self, requirement_id, employee_id=False, equipment_id=False,
        date_start=None, date_end=None,
    ):
        """Assign an employee or equipment to a requirement.

        ``date_start``/``date_end`` are optional ``YYYY-MM-DD`` days picked in
        the workspace; they default to the requirement range and must stay
        inside it (enforced by the assignment model's constraints).
        """
        self.ensure_one()
        requirement = self._get_planner_requirement(requirement_id)
        start = requirement.date_start or self.date_assign
        end = requirement.date_end or self.date_deadline
        if date_start:
            start = _local_dt_to_utc(self, date_start, start, 9)
        if date_end:
            end = _local_dt_to_utc(self, date_end, end, 18)
        if not start or not end:
            raise UserError(_(
                "Set task or requirement dates before assigning resources."
            ))
        self.env["project.task.resource.assignment"].create({
            "requirement_id": requirement.id,
            "employee_id": employee_id or False,
            "equipment_id": equipment_id or False,
            "date_start": start,
            "date_end": end,
        })
        return True

    def planner_estimate_assignment_hours(
        self, requirement_id, employee_id=False, equipment_id=False,
        date_start=None, date_end=None,
    ):
        """Working hours an assignment would cover for the given day range —
        same calendar logic as ``resource.assignment.planned_hours`` so the
        workspace can show the cost before creating the record."""
        self.ensure_one()
        requirement = self._get_planner_requirement(requirement_id)
        start = requirement.date_start or self.date_assign
        end = requirement.date_end or self.date_deadline
        if date_start:
            start = _local_dt_to_utc(self, date_start, start, 9)
        if date_end:
            end = _local_dt_to_utc(self, date_end, end, 18)
        if not start or not end or end <= start:
            return 0.0
        resource = False
        if employee_id:
            resource = self.env["hr.employee"].browse(employee_id).exists()
        elif equipment_id:
            resource = self.env["maintenance.equipment"].browse(
                equipment_id
            ).exists()
        calendar = (
            getattr(resource, "resource_calendar_id", False)
            or self.env.company.resource_calendar_id
        )
        if calendar:
            return calendar.get_work_hours_count(start, end, compute_leaves=True)
        return (end - start).total_seconds() / 3600.0

    def planner_unassign_resource(self, assignment_id):
        self.ensure_one()
        assignment = self.env["project.task.resource.assignment"].browse(
            assignment_id
        ).exists()
        if not assignment or assignment.task_id != self:
            raise UserError(_("This assignment does not belong to the task."))
        assignment.unlink()
        return True

    def planner_update_assignment(
        self, assignment_id, date_start=None, date_end=None
    ):
        """Move/resize an assignment from the timeline — same conversion and
        model constraints as creation."""
        self.ensure_one()
        assignment = self.env["project.task.resource.assignment"].browse(
            assignment_id
        ).exists()
        if not assignment or assignment.task_id != self:
            raise UserError(_("This assignment does not belong to the task."))
        vals = {}
        if date_start:
            vals["date_start"] = _local_dt_to_utc(
                self, date_start, assignment.date_start, 9
            )
        if date_end:
            vals["date_end"] = _local_dt_to_utc(
                self, date_end, assignment.date_end, 18
            )
        if vals:
            assignment.write(vals)
        return True


def _local_day_to_utc(record, day_str, existing_dt, fallback_hour):
    """Convert a local ``YYYY-MM-DD`` day to naive UTC, keeping the stored
    time-of-day when the task already had a date (so drags do not reset
    hours) and falling back to ``fallback_hour`` otherwise."""
    if not day_str:
        return False
    hour, minute = fallback_hour, 0
    if existing_dt:
        local_existing = fields.Datetime.context_timestamp(record, existing_dt)
        hour, minute = local_existing.hour, local_existing.minute
    local = datetime.strptime(day_str, "%Y-%m-%d").replace(hour=hour, minute=minute)
    tz = timezone(record.env.user.tz or "UTC")
    return tz.localize(local).astimezone(UTC).replace(tzinfo=None)


def _local_dt_to_utc(record, value, existing_dt=None, fallback_hour=9):
    """Like ``_local_day_to_utc`` but also accepts ``YYYY-MM-DD HH:MM[:SS]``
    local strings so timeline drags keep hour precision."""
    if not value:
        return False
    value = value.strip()
    if ":" in value:
        fmt = "%Y-%m-%d %H:%M:%S" if value.count(":") == 2 else "%Y-%m-%d %H:%M"
        local = datetime.strptime(value, fmt)
    else:
        hour, minute = fallback_hour, 0
        if existing_dt:
            local_existing = fields.Datetime.context_timestamp(record, existing_dt)
            hour, minute = local_existing.hour, local_existing.minute
        local = datetime.strptime(value, "%Y-%m-%d").replace(
            hour=hour, minute=minute
        )
    tz = timezone(record.env.user.tz or "UTC")
    return tz.localize(local).astimezone(UTC).replace(tzinfo=None)


def _planner_hours_per_day(record):
    """Working hours per calendar day used to sync duration with planned hours."""
    project = record.project_id if "project_id" in record._fields else False
    calendar = False
    if project and "resource_calendar_id" in project._fields:
        calendar = project.resource_calendar_id
    if not calendar:
        calendar = record.env.company.resource_calendar_id
    return (calendar.hours_per_day if calendar else 0.0) or 8.0
