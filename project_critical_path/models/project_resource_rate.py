# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectResourceRateTemplate(models.Model):
    """Reusable role+level → hourly rate table selected on a project.

    Rates are snapshot onto requirements when they are planned — later
    template edits never retroactively change planned costs (BRD §10).
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
    description = fields.Text()
    line_ids = fields.One2many(
        "project.resource.rate.template.line", "template_id", string="Rates",
    )

    def find_rate(self, role_id, level):
        """Hourly rate for ``role_id`` at ``level``; ``None`` when the
        combination is not defined in this template."""
        self.ensure_one()
        level = int(level or 0)
        for line in self.line_ids:
            if line.role_id.id == role_id and int(line.level) == level:
                return line.hourly_rate
        return None


class ProjectResourceRateTemplateLine(models.Model):
    _name = "project.resource.rate.template.line"
    _description = "Resource Rate Template Line"
    _order = "role_id, level"

    template_id = fields.Many2one(
        "project.resource.rate.template", required=True, ondelete="cascade", index=True,
    )
    role_id = fields.Many2one("project.resource.role", required=True, index=True)
    level = fields.Selection(
        [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5")],
        string="Level", required=True, default="1",
    )
    hourly_rate = fields.Float(required=True, default=0.0)
    currency_id = fields.Many2one(related="template_id.currency_id")

    _sql_constraints = [
        (
            "template_role_level_unique",
            "unique(template_id, role_id, level)",
            "A role can only have one rate per level within a template.",
        ),
    ]

    @api.constrains("hourly_rate")
    def _check_hourly_rate(self):
        for line in self:
            if line.hourly_rate < 0:
                raise ValidationError(_("The hourly rate cannot be negative."))
