# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    default_purchase_tolerance = fields.Float(
        string='Varsayılan Satınalma Toleransı (%)',
        digits='Discount',
        config_parameter='purchase_tolerance.default_purchase_tolerance',
        help="Ürün veya satınalma siparişi satırında özel tolerans tanımlanmadığında "
             "kullanılan varsayılan fazla teslimat toleransı.",
    )
