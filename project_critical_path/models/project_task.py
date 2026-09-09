# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProjectTask(models.Model):
    _inherit = "project.task"

    critical_early_start = fields.Float(string="Early Start", readonly=True)
    critical_early_finish = fields.Float(string="Early Finish", readonly=True)
    critical_late_start = fields.Float(string="Late Start", readonly=True)
    critical_late_finish = fields.Float(string="Late Finish", readonly=True)
    critical_slack = fields.Float(string="Slack", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks.mapped("project_id")._recalculate_critical_paths()
        return tasks

    def write(self, vals):
        affected_projects = self.mapped("project_id")
        result = super().write(vals)
        if {"project_id", "allocated_hours", "depend_on_ids", "dependent_ids"}.intersection(vals):
            (affected_projects | self.mapped("project_id"))._recalculate_critical_paths()
        return result

    def unlink(self):
        affected_projects = self.mapped("project_id")
        result = super().unlink()
        affected_projects._recalculate_critical_paths()
        return result
