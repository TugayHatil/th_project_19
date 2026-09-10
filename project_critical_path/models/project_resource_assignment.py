# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectTaskResourceAssignment(models.Model):
    _name = "project.task.resource.assignment"
    _description = "Project Task Resource Assignment"
    _order = "date_start, id"

    requirement_id = fields.Many2one(
        "project.task.resource.requirement", required=True, ondelete="cascade", index=True,
    )
    task_id = fields.Many2one(related="requirement_id.task_id", store=True, readonly=True, index=True)
    project_id = fields.Many2one(related="requirement_id.project_id", store=True, readonly=True, index=True)
    resource_category = fields.Selection(related="requirement_id.role_id.category", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Employee")
    equipment_id = fields.Many2one("maintenance.equipment", string="Equipment")
    date_start = fields.Date(string="Assignment Start")
    date_end = fields.Date(string="Assignment End")
    planned_hours = fields.Float(string="Planned Hours", required=True, default=0.0)

    @api.model_create_multi
    def create(self, vals_list):
        Requirement = self.env["project.task.resource.requirement"]
        for vals in vals_list:
            requirement_id = vals.get("requirement_id") or self.env.context.get("default_requirement_id")
            if requirement_id:
                requirement = Requirement.browse(requirement_id)
                vals.setdefault("date_start", requirement.date_start)
                vals.setdefault("date_end", requirement.date_end)
        return super().create(vals_list)

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
            if assignment.planned_hours < 0:
                raise ValidationError(_("Planned hours cannot be negative."))
            if assignment.date_start and assignment.date_end and assignment.date_start > assignment.date_end:
                raise ValidationError(_("Assignment end date must not be earlier than its start date."))
            if requirement.date_start and not assignment.date_start:
                raise ValidationError(_("Assignment start date is required for this resource requirement."))
            if requirement.date_end and not assignment.date_end:
                raise ValidationError(_("Assignment end date is required for this resource requirement."))
            if requirement.date_start and assignment.date_start and assignment.date_start < requirement.date_start:
                raise ValidationError(_("Assignment start must be within the requirement date range."))
            if requirement.date_end and assignment.date_end and assignment.date_end > requirement.date_end:
                raise ValidationError(_("Assignment end must be within the requirement date range."))

            assignments = requirement.assignment_ids
            resources = assignments.mapped("employee_id") if is_human else assignments.mapped("equipment_id")
            if len(resources) != len(assignments):
                raise ValidationError(_("The same resource cannot be assigned to one requirement more than once."))
            if len(assignments) > requirement.quantity + 0.000001:
                raise ValidationError(_("Assigned resource quantity cannot exceed the required quantity."))
            if sum(assignments.mapped("planned_hours")) > requirement.planned_hours + 0.000001:
                raise ValidationError(_("Assigned planned hours cannot exceed the required planned hours."))
