# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    manufacturer_ids = fields.One2many(
        related='product_variant_id.manufacturer_ids',
        string='Üreticiler',
        readonly=False,
    )
