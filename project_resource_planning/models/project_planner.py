# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.project_critical_path.models.project_planner import (
    _local_dt_to_utc,
    _serialize_planner_day,
    _serialize_planner_dt,
)


class ProjectProjectPlanner(models.Model):
    _inherit = "project.project"

    def _get_planner_resource_data(self, tasks):
        """Compact per-task resource summary for the planner row badges
        plus the project role list for the Filters dropdown."""
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
        return {
            "resources_by_task": resources_by_task,
            "roles": [
                {"id": role.id, "name": role.name, "category": role.category}
                for role in requirements.mapped("role_id")
            ],
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

