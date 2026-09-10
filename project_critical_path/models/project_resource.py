# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import api, fields, models


class ProjectResourceRole(models.Model):
    _name = "project.resource.role"
    _description = "Project Resource Role"
    _order = "category, name"

    name = fields.Char(required=True)
    category = fields.Selection([
        ("human", "Human"),
        ("equipment", "Equipment"),
    ], required=True, default="human")
    active = fields.Boolean(default=True)
    requirement_ids = fields.One2many("project.task.resource.requirement", "role_id")


class ProjectTaskResourceRequirement(models.Model):
    _name = "project.task.resource.requirement"
    _description = "Project Task Resource Requirement"
    _order = "date_start, role_id, id"

    task_id = fields.Many2one("project.task", required=True, ondelete="cascade", index=True)
    project_id = fields.Many2one(
        "project.project", related="task_id.project_id", store=True, index=True, readonly=True,
    )
    role_id = fields.Many2one("project.resource.role", required=True, index=True)
    quantity = fields.Float(required=True, default=1.0)
    date_start = fields.Datetime(string="Requirement Start")
    date_end = fields.Datetime(string="Requirement End")
    planned_hours = fields.Float(string="Planned Hours")
    description = fields.Text()
    assignment_ids = fields.One2many(
        "project.task.resource.assignment", "requirement_id", string="Assignments",
    )
    assigned_quantity = fields.Integer(compute="_compute_assignment_summary", string="Assigned Quantity")
    assigned_hours = fields.Float(compute="_compute_assignment_summary", string="Assigned Hours")
    assignment_status = fields.Selection([
        ("waiting", "Waiting"),
        ("partial", "Partial"),
        ("assigned", "Assigned"),
    ], compute="_compute_assignment_summary", string="Assignment Status")

    @api.depends("assignment_ids.employee_id", "assignment_ids.equipment_id", "assignment_ids.planned_hours")
    def _compute_assignment_summary(self):
        for requirement in self:
            assignments = requirement.assignment_ids
            requirement.assigned_quantity = len(assignments)
            requirement.assigned_hours = sum(assignments.mapped("planned_hours"))
            if not assignments:
                requirement.assignment_status = "waiting"
            elif (
                requirement.assigned_quantity >= requirement.quantity
                and requirement.assigned_hours >= requirement.planned_hours
            ):
                requirement.assignment_status = "assigned"
            else:
                requirement.assignment_status = "partial"

    def action_open_resource_assignments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Resource Assignments",
            "res_model": "project.task.resource.assignment",
            "view_mode": "list,form",
            "domain": [("requirement_id", "=", self.id)],
            "context": {"default_requirement_id": self.id},
        }

    def action_open_resource_planner(self):
        """Open the standard Gantt planner for this requirement's resource type."""
        self.ensure_one()
        category = self.role_id.category
        gantt_xmlid = (
            "project_task_resource_assignment_gantt_employee"
            if category == "human"
            else "project_task_resource_assignment_gantt_equipment"
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Resource Planner - %s" % self.role_id.display_name,
            "res_model": "project.task.resource.assignment",
            "view_mode": "gantt,list,form",
            "views": [
                (self.env.ref("project_critical_path.%s" % gantt_xmlid).id, "gantt"),
                (self.env.ref("project_critical_path.project_task_resource_assignment_list").id, "list"),
                (self.env.ref("project_critical_path.project_task_resource_assignment_form").id, "form"),
            ],
            "domain": [
                ("resource_category", "=", category),
                ("date_start", "<=", self.date_end),
                ("date_end", ">=", self.date_start),
            ],
            "context": {
                "default_requirement_id": self.id,
                "default_date_start": self.date_start,
                "default_date_end": self.date_end,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        Task = self.env["project.task"]
        for vals in vals_list:
            task_id = vals.get("task_id") or self.env.context.get("default_task_id")
            if task_id:
                task = Task.browse(task_id)
                if "date_start" not in vals and "date_assign" in task._fields:
                    vals["date_start"] = task.date_assign if task.date_assign else False
                if "date_end" not in vals and "date_deadline" in task._fields:
                    vals["date_end"] = task.date_deadline if task.date_deadline else False
        requirements = super().create(vals_list)
        requirements.mapped("project_id")._recalculate_resource_plan()
        return requirements

    def write(self, vals):
        affected_projects = self.mapped("project_id")
        result = super().write(vals)
        if {"task_id", "role_id", "quantity", "planned_hours"}.intersection(vals):
            (affected_projects | self.mapped("project_id"))._recalculate_resource_plan()
        return result

    def unlink(self):
        projects = self.mapped("project_id")
        result = super().unlink()
        projects._recalculate_resource_plan()
        return result


class ProjectResourcePlanSummary(models.Model):
    _name = "project.resource.plan.summary"
    _description = "Project Resource Plan Summary"
    _order = "role_id"

    project_id = fields.Many2one("project.project", required=True, ondelete="cascade", index=True)
    role_id = fields.Many2one("project.resource.role", required=True, ondelete="cascade")
    total_quantity = fields.Float(readonly=True)
    total_planned_hours = fields.Float(readonly=True)
