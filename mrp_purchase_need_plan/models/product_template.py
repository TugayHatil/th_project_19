# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # BRD §4.1 — days the internal purchase process needs before the
    # supplier lead time starts. Empty = fall back to the global default
    # (Settings > Purchase > Default Purchase Process Days).
    x_purchase_process_days = fields.Integer(
        string="Purchase Process Days",
        help="Number of days needed by the internal purchase process for "
             "this product. When left empty, the default value configured "
             "in Purchase settings is used.",
    )

    @api.constrains("x_purchase_process_days")
    def _check_purchase_process_days(self):
        for tmpl in self:
            if tmpl.x_purchase_process_days and tmpl.x_purchase_process_days < 0:
                raise ValidationError(
                    self.env._("Purchase Process Days cannot be negative.")
                )
