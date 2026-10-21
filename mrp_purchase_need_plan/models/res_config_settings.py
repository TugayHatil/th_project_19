# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # BRD §4.2 — company-wide fallback used when the product card does
    # not define x_purchase_process_days.
    purchase_need_process_days = fields.Integer(
        string="Varsayılan Satınalma için Gerekli Gün",
        config_parameter="mrp_purchase_need_plan.default_process_days",
        help="Şirket içi satınalma süreci için varsayılan gün sayısı. "
             "Ürün kartında değer tanımlanmamışsa Malzeme İhtiyaç "
             "Planlama ekranı bu değeri kullanır.",
    )

    @api.constrains("purchase_need_process_days")
    def _check_purchase_need_process_days(self):
        for rec in self:
            if rec.purchase_need_process_days and rec.purchase_need_process_days < 0:
                raise ValidationError(
                    self.env._("Varsayılan Satınalma için Gerekli Gün negatif olamaz.")
                )
