# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectBaselineTitle(models.Model):
    """Predefined titles selectable when saving a plan baseline (BRD).

    Titles are managed under Project ▸ Configuration and can be
    activated/deactivated; only active ones are offered in the Planner's
    Baseline Save dialog. The chosen title is appended to the generated
    version name — e.g. ``v1.20 - Revize İş Programı``.
    """

    _name = "project.baseline.title"
    _description = "Baseline Title"
    _order = "name, id"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)

    @api.constrains("name")
    def _check_name_length(self):
        for title in self:
            if title.name and len(title.name) > 25:
                raise ValidationError(
                    _("The baseline title cannot exceed 25 characters.")
                )
