# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_long_term_production_planning = fields.Boolean(
        string="Use in Long-Term Production Planning",
        default=False,
        help="Products flagged with this option are listed on the "
             "Manufacturing > Planning > Long-Term Production Planning screen.",
    )
