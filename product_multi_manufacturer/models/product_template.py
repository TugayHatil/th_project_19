# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Not a 'related' field on purpose: writing through a related field would
    # trigger modified() searches on the non-stored product_variant_id and crash.
    manufacturer_ids = fields.One2many(
        'product.manufacturer',
        compute='_compute_manufacturer_ids',
        inverse='_inverse_manufacturer_ids',
        string='Üreticiler',
        readonly=False,
    )

    @api.depends('product_variant_ids')
    def _compute_manufacturer_ids(self):
        for template in self:
            template.manufacturer_ids = template.product_variant_id.manufacturer_ids

    def _inverse_manufacturer_ids(self):
        for template in self:
            variant = template.product_variant_id
            if variant:
                variant.manufacturer_ids = template.manufacturer_ids
