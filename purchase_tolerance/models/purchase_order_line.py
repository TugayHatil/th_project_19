# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

TOLERANCE_PRECISION = 2


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    purchase_tolerance = fields.Float(
        string='Satınalma Toleransı (%)',
        digits='Discount',
        compute='_compute_purchase_tolerance',
        store=True,
        readonly=False,
        copy=True,
        help="Sipariş miktarının üzerinde mal kabul edilebilecek fazla teslimat "
             "yüzdesi. Sipariş oluşturulurken ürün / genel ayardan otomatik gelir; "
             "yalnızca Satınalma Yöneticisi değiştirebilir.",
    )
    max_accepted_qty = fields.Float(
        string='Maks. Kabul Edilebilir Miktar',
        compute='_compute_max_accepted_qty',
        digits='Product Unit',
    )
    can_edit_purchase_tolerance = fields.Boolean(
        compute='_compute_can_edit_purchase_tolerance',
    )

    def _compute_can_edit_purchase_tolerance(self):
        is_manager = self.env.user.has_group('purchase.group_purchase_manager')
        for line in self:
            line.can_edit_purchase_tolerance = is_manager

    def _get_product_purchase_tolerance(self, product):
        product_tmpl = product.product_tmpl_id
        return product_tmpl.purchase_tolerance if product_tmpl else 0.0

    def _get_default_purchase_tolerance(self):
        self.ensure_one()
        if not self.product_id:
            return 0.0
        return self._get_product_purchase_tolerance(self.product_id)

    @api.depends('product_id')
    def _compute_purchase_tolerance(self):
        for line in self:
            if not line.product_id or line.display_type:
                line.purchase_tolerance = 0.0
            else:
                line.purchase_tolerance = line._get_default_purchase_tolerance()

    @api.depends('product_qty', 'purchase_tolerance')
    def _compute_max_accepted_qty(self):
        for line in self:
            line.max_accepted_qty = line.product_qty * (1 + line.purchase_tolerance / 100.0)

    @api.constrains('purchase_tolerance')
    def _check_purchase_tolerance(self):
        for line in self:
            if line.purchase_tolerance < 0:
                raise UserError(_('Satınalma toleransı negatif olamaz.'))

    def _check_purchase_tolerance_change(self, tolerance, product):
        """Varsayılan değer dışında bir tolerans ancak Satınalma Yöneticisi
        tarafından girilebilir."""
        if self.env.user.has_group('purchase.group_purchase_manager') \
                or self.env.context.get('bypass_purchase_tolerance_guard'):
            return
        expected = self._get_product_purchase_tolerance(product) if product else 0.0
        if float_compare(float(tolerance or 0.0), expected,
                         precision_digits=TOLERANCE_PRECISION) != 0:
            raise UserError(_(
                'Satınalma toleransı yalnızca Satınalma Yöneticisi tarafından '
                'değiştirilebilir.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'purchase_tolerance' in vals:
                product = self.env['product.product'].browse(vals.get('product_id'))
                self._check_purchase_tolerance_change(vals['purchase_tolerance'], product)
        return super().create(vals_list)

    def write(self, vals):
        old_tolerance = {}
        if 'purchase_tolerance' in vals:
            for line in self:
                product = self.env['product.product'].browse(vals['product_id']) \
                    if 'product_id' in vals else line.product_id
                line._check_purchase_tolerance_change(vals['purchase_tolerance'], product)
                old_tolerance[line.id] = line.purchase_tolerance
        res = super().write(vals)
        for line_id, old_value in old_tolerance.items():
            line = self.browse(line_id)
            new_value = float(vals['purchase_tolerance'] or 0.0)
            if float_compare(old_value, new_value,
                             precision_digits=TOLERANCE_PRECISION) != 0:
                line.order_id.message_post(body=_(
                    'Satınalma Toleransı: %(old)s%% → %(new)s%% (%(product)s)',
                    old=old_value, new=new_value,
                    product=line.product_id.display_name))
        return res
