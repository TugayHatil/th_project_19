# -*- coding: utf-8 -*-
from odoo import fields, models


class QualityPoint(models.Model):
    _inherit = 'quality.point'

    auto_purchase_tmpl_id = fields.Many2one(
        'product.template', string='Otomatik Satınalma KK Ürünü',
        index=True, copy=False, readonly=True, ondelete='set null',
        help='Bu kalite kontrol noktası, ürün kartındaki "Satınalma KK" '
             'işaretiyle otomatik oluşturulmuştur.')

    _sql_constraints = [
        ('auto_purchase_tmpl_uniq', 'unique(auto_purchase_tmpl_id)',
         'Her ürün için yalnızca bir otomatik kalite kontrol noktası '
         'oluşturulabilir.'),
    ]
