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
    date_start = fields.Date(string="Requirement Start")
    date_end = fields.Date(string="Requirement End")
    planned_hours = fields.Float(string="Planned Hours")
    description = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        Task = self.env["project.task"]
        for vals in vals_list:
            task_id = vals.get("task_id") or self.env.context.get("default_task_id")
            if task_id:
                task = Task.browse(task_id)
                if "date_start" not in vals and "date_assign" in task._fields:
                    vals["date_start"] = fields.Date.to_date(task.date_assign) if task.date_assign else False
                if "date_end" not in vals and "date_deadline" in task._fields:
                    vals["date_end"] = fields.Date.to_date(task.date_deadline) if task.date_deadline else False
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
