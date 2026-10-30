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

    @api.model_create_multi
    def create(self, vals_list):
        # Hesaplanan o2m'nin inverse'i create sırasında çalışmaz; komutları
        # kaydırdıktan sonra varyantın gerçek o2m alanına uygula.
        mfr_commands = [vals.pop('manufacturer_ids', None)
                        for vals in vals_list]
        templates = super().create(vals_list)
        for template, commands in zip(templates, mfr_commands):
            if commands:
                template.product_variant_id.write(
                    {'manufacturer_ids': commands})
                template.invalidate_recordset(['manufacturer_ids'])
        return templates
