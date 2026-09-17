# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectResourceRateTemplate(models.Model):
    """Currency + single hourly planning rate selected on a project.

    The rate is snapshot onto the project (and onto each requirement) when
    it is applied — later template edits never retroactively change planned
    costs (BRD §10).
    """

    _name = "project.resource.rate.template"
    _description = "Resource Rate Template"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.company.currency_id,
    )
    hourly_rate = fields.Float(string="Hourly Rate", required=True, default=0.0)
    description = fields.Text()

    @api.constrains("hourly_rate")
    def _check_hourly_rate(self):
        for template in self:
            if template.hourly_rate < 0:
                raise ValidationError(_("The hourly rate cannot be negative."))
