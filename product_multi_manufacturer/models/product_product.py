# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductProduct(models.Model):
    _inherit = 'product.product'

    manufacturer_ids = fields.One2many(
        'product.manufacturer',
        'product_id',
        string='Üreticiler',
    )
