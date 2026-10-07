# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _default_purchase_tolerance(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'purchase_tolerance.default_purchase_tolerance')
        return float(param or 0.0)

    purchase_tolerance = fields.Float(
        string='Satınalma Toleransı (%)',
        digits='Discount',
        default=_default_purchase_tolerance,
        help="Bu ürün için sipariş miktarının üzerinde kabul edilebilecek fazla "
             "teslimat yüzdesi. %0 fazla teslimata hiç izin vermez. Yeni üründe "
             "Satınalma Ayarları'ndaki varsayılan tolerans otomatik gelir; "
             "genel ayar sonradan değişse mevcut ürünler etkilenmez.",
    )

    @api.constrains('purchase_tolerance')
    def _check_purchase_tolerance(self):
        for product in self:
            if product.purchase_tolerance < 0:
                raise ValidationError(_('Satınalma toleransı negatif olamaz.'))
