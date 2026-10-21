# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # BRD §4.2 — company-wide fallback used when the product card does
    # not define x_purchase_process_days.
    purchase_need_process_days = fields.Integer(
        string="Default Purchase Process Days",
        config_parameter="mrp_purchase_need_plan.default_process_days",
        help="Default number of days needed by the internal purchase "
             "process. Used by the Material Need Planning screen when the "
             "product card does not define its own value.",
    )

    @api.constrains("purchase_need_process_days")
    def _check_purchase_need_process_days(self):
        for rec in self:
            if rec.purchase_need_process_days and rec.purchase_need_process_days < 0:
                raise ValidationError(
                    self.env._("Default Purchase Process Days cannot be negative.")
                )
