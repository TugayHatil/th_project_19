# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Bilinçli olarak related değil: related üzerinden yazma, store
    # olmayan product_variant_id için modified() araması yapar ve patlar.
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
        # yeni yazılan satırların sonraki okumada görünmesi için
        self.invalidate_recordset(['manufacturer_ids'])
