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
    produce_delay = fields.Integer(
        string="Üretim Süresi (Gün)",
        default=0,
        help="Ürünün üretiminin kaç gün sürdüğü. Reçete patlamasında "
             "bileşen ihtiyaç tarihi, ana ürünün ihtiyaç tarihinden bu "
             "kadar gün öncesine alınır.",
    )
    x_mip_responsible_id = fields.Many2one(
        "res.users",
        string="MİP Sorumlusu",
        help="Bu ürünün malzeme ihtiyaç planlamasından sorumlu kullanıcı.",
    )
    x_sa_responsible_id = fields.Many2one(
        "res.users",
        string="SA Sorumlusu",
        help="Bu ürünün satınalma sürecinden sorumlu kullanıcı.",
    )

    @api.constrains("x_purchase_process_days")
    def _check_purchase_process_days(self):
        for tmpl in self:
            if tmpl.x_purchase_process_days and tmpl.x_purchase_process_days < 0:
                raise ValidationError(
                    self.env._("Satınalma için Gerekli Gün negatif olamaz.")
                )

    # routes, lead days and storable flags feed the plan — any product
    # master-data change invalidates the cached plan
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return recs

    def write(self, vals):
        res = super().write(vals)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return res


class ProductSupplierinfo(models.Model):
    _inherit = "product.supplierinfo"

    # supplier lead times enter the purchase-start calculation
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return recs

    def write(self, vals):
        res = super().write(vals)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return res

    def unlink(self):
        res = super().unlink()
        self.env["mrp.purchase.need"]._bump_plan_version()
        return res
