# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    quality_purchase_ok = fields.Boolean(
        string='Satınalma KK', default=False, copy=True,
        help='İşaretlendiğinde bu ürün gelen transfer satırlarında kalite '
             'ekibine gönderilmek üzere işaretlenebilir.')
