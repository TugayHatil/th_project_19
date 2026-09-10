# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.tools import format_datetime


class ProjectResourcePlanner(models.TransientModel):
    """A temporary Team Planner built directly from employees or equipment."""

    _name = "project.resource.planner"
    _description = "Project Resource Planner"

    requirement_id = fields.Many2one(
        "project.task.resource.requirement", required=True, readonly=True,
    )
    resource_category = fields.Selection(related="requirement_id.role_id.category", readonly=True)
    date_start = fields.Datetime(related="requirement_id.date_start", readonly=True)
    date_end = fields.Datetime(related="requirement_id.date_end", readonly=True)
    line_ids = fields.One2many("project.resource.planner.line", "planner_id", readonly=True)

    @api.model
    def create_for_requirement(self, requirement):
        planner = self.create({"requirement_id": requirement.id})
        planner._build_lines()
        return planner

    def _build_lines(self):
        Assignment = self.env["project.task.resource.assignment"]
        Line = self.env["project.resource.planner.line"]
        for planner in self:
            Line.search([("planner_id", "=", planner.id)]).unlink()
            if planner.resource_category == "human":
                resources = self.env["hr.employee"].search([
                    ("active", "=", True),
                    ("resource_role_ids", "in", planner.requirement_id.role_id.ids),
                ])
                resource_field = "employee_id"
            else:
                resources = self.env["maintenance.equipment"].search([("active", "=", True)])
                resource_field = "equipment_id"
            assignments = Assignment.search([
                ("resource_category", "=", planner.resource_category),
                ("date_start", "<=", planner.date_end),
                ("date_end", ">=", planner.date_start),
            ], order="date_start, id")
            values = []
            for resource in resources:
                bookings = assignments.filtered(lambda assignment: assignment[resource_field] == resource)
                booked_hours = planner._get_booked_hours(resource, bookings)
                available_hours = planner._get_available_hours(resource)
                if not bookings:
                    availability_status, availability_order = "fully_available", 0
                elif available_hours and booked_hours >= available_hours:
                    availability_status, availability_order = "unavailable", 2
                else:
                    availability_status, availability_order = "partially_available", 1
                values.append({
                    "planner_id": planner.id,
                    resource_field: resource.id,
                    "availability_status": availability_status,
                    "availability_order": availability_order,
                    "available_hours": available_hours,
                    "booked_hours": booked_hours,
                    "assignment_ids": [(6, 0, bookings.ids)],
                    "booking_summary": "\n".join(
                        "%s: %s – %s" % (
                            assignment.task_id.display_name,
                            format_datetime(self.env, assignment.date_start),
                            format_datetime(self.env, assignment.date_end),
                        )
                        for assignment in bookings
                    ) or _("Available"),
                })
            Line.create(values)

    def _get_booked_hours(self, resource, bookings):
        self.ensure_one()
        calendar = getattr(resource, "resource_calendar_id", False) or self.env.company.resource_calendar_id
        booked_hours = 0.0
        for booking in bookings:
            start = max(booking.date_start, self.date_start)
            end = min(booking.date_end, self.date_end)
            if calendar:
                booked_hours += calendar.get_work_hours_count(start, end, compute_leaves=True)
            else:
                booked_hours += (end - start).total_seconds() / 3600.0
        return booked_hours

    def _get_available_hours(self, resource):
        self.ensure_one()
        calendar = getattr(resource, "resource_calendar_id", False) or self.env.company.resource_calendar_id
        if calendar and self.date_start and self.date_end:
            return calendar.get_work_hours_count(self.date_start, self.date_end, compute_leaves=True)
        if self.date_start and self.date_end:
            return (self.date_end - self.date_start).total_seconds() / 3600.0
        return 0.0

    def action_open_timeline(self):
        self.ensure_one()
        return self.requirement_id.action_open_resource_timeline()


class ProjectResourcePlannerLine(models.TransientModel):
    _name = "project.resource.planner.line"
    _description = "Project Resource Planner Line"
    _order = "availability_order, resource_name"

    planner_id = fields.Many2one("project.resource.planner", required=True, ondelete="cascade")
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    equipment_id = fields.Many2one("maintenance.equipment", string="Equipment", readonly=True)
    resource_name = fields.Char(compute="_compute_resource_name", store=True, readonly=True)
    availability_status = fields.Selection([
        ("fully_available", "Fully Available"),
        ("partially_available", "Partially Available"),
        ("unavailable", "Unavailable"),
    ], readonly=True)
    availability_order = fields.Integer(readonly=True)
    available_hours = fields.Float(readonly=True)
    booked_hours = fields.Float(readonly=True)
    booking_summary = fields.Text(readonly=True)
    assignment_ids = fields.Many2many(
        "project.task.resource.assignment",
        "project_res_planner_assign_rel",
        "planner_line_id",
        "assignment_id",
        readonly=True,
    )

    @api.depends("employee_id", "equipment_id")
    def _compute_resource_name(self):
        for line in self:
            line.resource_name = (line.employee_id or line.equipment_id).display_name

    def action_assign_resource(self):
        self.ensure_one()
        requirement = self.planner_id.requirement_id
        return {
            "type": "ir.actions.act_window",
            "name": _("Assign Resource"),
            "res_model": "project.task.resource.assignment",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_requirement_id": requirement.id,
                "default_employee_id": self.employee_id.id,
                "default_equipment_id": self.equipment_id.id,
                "default_date_start": requirement.date_start,
                "default_date_end": requirement.date_end,
            },
        }

    def action_open_resource_timeline(self):
        self.ensure_one()
        requirement = self.planner_id.requirement_id
        resource_domain = (
            [("employee_id", "=", self.employee_id.id)]
            if self.employee_id else [("equipment_id", "=", self.equipment_id.id)]
        )
        action = requirement.action_open_resource_timeline()
        action["domain"] += resource_domain
        return action
