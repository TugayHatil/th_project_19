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
            # False when project_resource_planning is not installed — the
            # workspace hides the Resource Board / Material Plan / inspector
            # resource UI instead of calling missing models.
            "has_resource_planning": (
                self.env.registry.get("project.task.resource.requirement") is not None
            ),
        }

    def _get_planner_resource_data(self, tasks):
        """Resource payload for the planner rows and the meta block.

        Empty hook in the core addon — ``project_resource_planning``
        overrides it with the per-task human/equipment/open badge counts
        and the project role list. The planner payload always carries the
        same keys, simply empty, so the UI code never has to guess.
        """
        return {"resources_by_task": {}, "roles": []}

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
        # Compact per-task resource summary for the row badges — real data
        # comes from the project_resource_planning hook; standalone core
        # ships empty badges.
        resource_data = self._get_planner_resource_data(ordered)
        resources_by_task = resource_data["resources_by_task"]
        # Finish Variance (BRD): effective close per task — a leaf's own
        # date_done; a parent's the latest child close once every child
        # is done. Visual only — scheduling and CPM never read this.
        done_by_task = {
            task.id: task._planner_effective_done() for task in ordered
        }
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
            "roles": resource_data["roles"],
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
                    # Finish Variance (BRD): own close for leaves; for
                    # parents the latest close across fully-done children.
                    "date_done": (
                        _serialize_planner_day(task, done_by_task[task.id])
                        if done_by_task[task.id] else False
                    ),
                    "dt_done": (
                        _serialize_planner_dt(task, done_by_task[task.id])
                        if done_by_task[task.id] else False
                    ),
                    # Group By keys (BRD Standard Filters) — display values
                    # only; filtering itself runs on real fields via domain.
                    "user_ids": task.user_ids.ids,
                    "user_names": task.user_ids.mapped("name"),
                    "stage_name": task.stage_id.name or "",
                    **task._planner_resource_fields(),
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
        effective_done = self._planner_effective_done()
        return {
            "task": {
                "id": self.id,
                "name": self.name or "",
                "wbs_code": self.wbs_code or "",
                "is_critical": bool(self.is_critical),
                "critical_slack": self.critical_slack or 0.0,
                "is_done": self.state == "1_done",
                # Finish Variance (BRD): parent rows report the latest
                # fully-done child close, same as the timeline payload.
                "date_done": (
                    _serialize_planner_day(self, effective_done)
                    if effective_done else False
                ),
                "dt_done": (
                    _serialize_planner_dt(self, effective_done)
                    if effective_done else False
                ),
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
