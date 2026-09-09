# -*- coding: utf-8 -*-

from odoo import api, models


class ProjectTask(models.Model):
    _inherit = "project.task"

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
