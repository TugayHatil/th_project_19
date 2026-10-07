# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    use_default_purchase_tolerance = fields.Boolean(
        string='Varsayılan Satınalma Toleransını Kullan',
        default=True,
        help="İşaretliyse Satınalma Ayarları'ndaki varsayılan tolerans kullanılır. "
             "Kaldırılırsa bu ürüne özel bir tolerans girilebilir (%0 dahil).",
    )
    purchase_tolerance = fields.Float(
        string='Satınalma Toleransı (%)',
        digits='Discount',
        help="Bu ürün için sipariş miktarının üzerinde kabul edilebilecek fazla "
             "teslimat yüzdesi. %0 fazla teslimata hiç izin vermez.",
    )

    @api.constrains('purchase_tolerance')
    def _check_purchase_tolerance(self):
        for product in self:
            if product.purchase_tolerance < 0:
                raise ValidationError(_('Satınalma toleransı negatif olamaz.'))
