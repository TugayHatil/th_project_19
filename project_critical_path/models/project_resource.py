# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectResourceRole(models.Model):
    _name = "project.resource.role"
    _description = "Project Resource Role"
    _order = "category, name"

    name = fields.Char(required=True)
    category = fields.Selection([
        ("human", "Human"),
        ("equipment", "Equipment"),
    ], required=True, default="human")
    # Same 5-star Selection as hr.employee.priority so the priority widget
    # renders identically (BRD §4/§26).
    priority = fields.Selection(
        [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5")],
        string="Level", required=True, default="1",
    )
    active = fields.Boolean(default=True)
    requirement_ids = fields.One2many("project.task.resource.requirement", "role_id")


class ProjectTaskResourceRequirement(models.Model):
    _name = "project.task.resource.requirement"
    _description = "Project Task Resource Requirement"
    _order = "date_start, role_id, id"
    _rec_name = "name"

    task_id = fields.Many2one("project.task", required=True, ondelete="cascade", index=True)
    project_id = fields.Many2one(
        "project.project", related="task_id.project_id", store=True, index=True, readonly=True,
    )
    role_id = fields.Many2one("project.resource.role", required=True, index=True)
    # Level is a property of the role — it is never picked manually on a
    # requirement, the role's 5-star level applies automatically (BRD §4).
    level = fields.Selection(
        related="role_id.priority", string="Level", store=True, readonly=True,
    )
    quantity = fields.Float(required=True, default=1.0)
    date_start = fields.Datetime(string="Requirement Start")
    date_end = fields.Datetime(string="Requirement End")
    planned_hours = fields.Float(string="Planned Hours")
    description = fields.Text()
    name = fields.Char(compute="_compute_name", store=True, readonly=True)
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
    # Cost planning (BRD): rate snapshot from the project's rate template —
    # stored, so later template edits never move existing planned costs.
    hourly_rate = fields.Float(string="Hourly Rate")
    currency_id = fields.Many2one(
        "res.currency", compute="_compute_currency_id", store=True, readonly=True,
    )
    planned_cost = fields.Monetary(
        string="Planned Cost", compute="_compute_planned_cost",
        currency_field="currency_id", store=True, readonly=True,
    )

    @api.depends(
        "project_id.resource_currency_id",
        "project_id.resource_rate_template_id.currency_id",
    )
    def _compute_currency_id(self):
        for requirement in self:
            requirement.currency_id = (
                requirement.project_id.resource_currency_id
                or requirement.project_id.resource_rate_template_id.currency_id
                or self.env.company.currency_id
            )

    @api.depends("quantity", "planned_hours", "hourly_rate")
    def _compute_planned_cost(self):
        for requirement in self:
            requirement.planned_cost = (
                (requirement.quantity or 0.0)
                * (requirement.planned_hours or 0.0)
                * (requirement.hourly_rate or 0.0)
            )

    def _resolve_hourly_rate(self):
        """Planning rate snapshot for this requirement.

        The single template rate is copied onto the project when the
        template is selected; requirements read the project snapshot so a
        later template edit never moves existing planned costs (BRD §10).
        Returns ``None`` when the project has no template — no planned cost
        is computed then (BRD §24).
        """
        project = self.project_id
        if not project.resource_rate_template_id:
            return None
        return project.resource_hourly_rate or project.resource_rate_template_id.hourly_rate

    @api.constrains("hourly_rate")
    def _check_hourly_rate(self):
        for requirement in self:
            if requirement.hourly_rate < 0:
                raise ValidationError(_("The hourly rate cannot be negative."))

    @api.onchange("role_id")
    def _onchange_role_id(self):
        if self.role_id:
            rate = self._resolve_hourly_rate()
            if rate is not None:
                self.hourly_rate = rate

    @api.depends("task_id.display_name", "role_id.name")
    def _compute_name(self):
        for requirement in self:
            requirement.name = " - ".join(
                value for value in (requirement.task_id.display_name, requirement.role_id.name) if value
            )

    @api.depends("assignment_ids.employee_id", "assignment_ids.equipment_id", "assignment_ids.planned_hours")
    def _compute_assignment_summary(self):
        for requirement in self:
            assignments = requirement.assignment_ids
            res_field = "employee_id" if requirement.role_id.category == "human" else "equipment_id"
            requirement.assigned_quantity = len(assignments.mapped(res_field))
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
            "views": [[False, "list"], [False, "form"]],
            "domain": [("requirement_id", "=", self.id)],
            "context": {"default_requirement_id": self.id},
        }

    def action_open_resource_planner(self):
        """Open the real-resource Team Planner, including unassigned resources."""
        self.ensure_one()
        planner = self.env["project.resource.planner"].create_for_requirement(self)
        return {
            "type": "ir.actions.act_window",
            "name": "Resource Planner - %s" % self.role_id.display_name,
            "res_model": "project.resource.planner",
            "res_id": planner.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
        }

    def action_open_resource_timeline(self):
        """Open the standard Gantt timeline of existing bookings."""
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
        for requirement, vals in zip(requirements, vals_list):
            if not vals.get("hourly_rate"):
                rate = requirement._resolve_hourly_rate()
                if rate is not None:
                    requirement.hourly_rate = rate
        requirements.mapped("project_id")._recalculate_resource_plan()
        return requirements

    def write(self, vals):
        affected_projects = self.mapped("project_id")
        result = super().write(vals)
        if {"task_id", "role_id"}.intersection(vals) and "hourly_rate" not in vals:
            for requirement in self:
                rate = requirement._resolve_hourly_rate()
                if rate is not None:
                    requirement.write({"hourly_rate": rate})
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
    currency_id = fields.Many2one(related="project_id.resource_cost_currency_id")
    total_planned_cost = fields.Monetary(
        string="Planned Cost", currency_field="currency_id", readonly=True,
    )
