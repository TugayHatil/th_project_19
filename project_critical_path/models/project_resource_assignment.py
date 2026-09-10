# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectTaskResourceAssignment(models.Model):
    _name = "project.task.resource.assignment"
    _description = "Project Task Resource Assignment"
    _order = "date_start, id"
    _rec_name = "name"

    requirement_id = fields.Many2one(
        "project.task.resource.requirement", required=True, ondelete="cascade", index=True,
    )
    task_id = fields.Many2one(related="requirement_id.task_id", store=True, readonly=True, index=True)
    project_id = fields.Many2one(related="requirement_id.project_id", store=True, readonly=True, index=True)
    resource_category = fields.Selection(related="requirement_id.role_id.category", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Employee")
    equipment_id = fields.Many2one("maintenance.equipment", string="Equipment")
    date_start = fields.Datetime(string="Assignment Start", required=True)
    date_end = fields.Datetime(string="Assignment End", required=True)
    planned_hours = fields.Float(
        string="Assigned Hours", compute="_compute_planned_hours", store=True, readonly=True,
    )
    name = fields.Char(compute="_compute_name", store=True, readonly=True)

    @api.depends("task_id.display_name", "employee_id.name", "equipment_id.name")
    def _compute_name(self):
        for assignment in self:
            assignment.name = assignment.task_id.display_name or assignment.employee_id.name or assignment.equipment_id.name

    def action_open_task(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "res_id": self.task_id.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model_create_multi
    def create(self, vals_list):
        Requirement = self.env["project.task.resource.requirement"]
        for vals in vals_list:
            requirement_id = vals.get("requirement_id") or self.env.context.get("default_requirement_id")
            if requirement_id:
                requirement = Requirement.browse(requirement_id)
                if "date_start" not in vals and requirement.date_start:
                    vals["date_start"] = requirement.date_start
                if "date_end" not in vals and requirement.date_end:
                    vals["date_end"] = requirement.date_end
            vals.pop("planned_hours", None)
        return super().create(vals_list)

    @api.depends("date_start", "date_end", "employee_id.resource_calendar_id")
    def _compute_planned_hours(self):
        for assignment in self:
            if not assignment.date_start or not assignment.date_end or assignment.date_end <= assignment.date_start:
                assignment.planned_hours = 0.0
                continue
            calendar = assignment.employee_id.resource_calendar_id or self.env.company.resource_calendar_id
            if calendar:
                assignment.planned_hours = calendar.get_work_hours_count(
                    assignment.date_start, assignment.date_end, compute_leaves=True,
                )
            else:
                assignment.planned_hours = (assignment.date_end - assignment.date_start).total_seconds() / 3600.0

    @api.constrains(
        "requirement_id", "employee_id", "equipment_id", "date_start", "date_end", "planned_hours",
    )
    def _check_assignment(self):
        for assignment in self:
            requirement = assignment.requirement_id
            is_human = requirement.role_id.category == "human"
            if is_human and (not assignment.employee_id or assignment.equipment_id):
                raise ValidationError(_("Human resource requirements require exactly one employee."))
            if not is_human and (not assignment.equipment_id or assignment.employee_id):
                raise ValidationError(_("Equipment resource requirements require exactly one equipment record."))
            if assignment.date_end <= assignment.date_start:
                raise ValidationError(_("Assignment end date must not be earlier than its start date."))
            if requirement.date_start and assignment.date_start < requirement.date_start:
                raise ValidationError(_("Assignment start must be within the requirement date range."))
            if requirement.date_end and assignment.date_end > requirement.date_end:
                raise ValidationError(_("Assignment end must be within the requirement date range."))

            assignments = requirement.assignment_ids
            resources = assignments.mapped("employee_id") if is_human else assignments.mapped("equipment_id")
            if len(resources) != len(assignments):
                raise ValidationError(_("The same resource cannot be assigned to one requirement more than once."))
            if len(assignments) > requirement.quantity + 0.000001:
                raise ValidationError(_("Assigned resource quantity cannot exceed the required quantity."))
            if sum(assignments.mapped("planned_hours")) > requirement.planned_hours + 0.000001:
                raise ValidationError(_("Assigned planned hours cannot exceed the required planned hours."))
