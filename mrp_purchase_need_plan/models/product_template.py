# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # BRD §4.1 — days the internal purchase process needs before the
    # supplier lead time starts. Empty = fall back to the global default
    # (Settings > Purchase > Default Purchase Process Days).
    x_purchase_process_days = fields.Integer(
        string="Satınalma için Gerekli Gün",
        help="Bu ürün için şirket içi satınalma sürecinin gerektirdiği gün "
             "sayısı. Boş bırakılırsa Satınalma ayarlarındaki varsayılan "
             "değer kullanılır.",
    )
    # days production needs from its start until the product is ready —
    # BoM-exploded component needs are dated this many days before the
    # parent's own need date (Odoo 19 removed the core produce_delay)
    produce_delay = fields.Float(
        string="Üretim Süresi (Gün)",
        default=0.0,
        help="Ürünün üretiminin kaç gün sürdüğü. Reçete patlamasında "
             "bileşen ihtiyaç tarihi, ana ürünün ihtiyaç tarihinden bu "
             "kadar gün öncesine alınır.",
    )

    @api.constrains("x_purchase_process_days")
    def _check_purchase_process_days(self):
        for tmpl in self:
            if tmpl.x_purchase_process_days and tmpl.x_purchase_process_days < 0:
                raise ValidationError(
                    self.env._("Satınalma için Gerekli Gün negatif olamaz.")
                )
