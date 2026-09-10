# -*- coding: utf-8 -*-

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    resource_role_ids = fields.Many2many(
        "project.resource.role",
        "project_employee_resource_role_rel",
        "employee_id",
        "role_id",
        string="Resource Roles",
    )
