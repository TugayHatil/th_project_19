# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models

from .product_supplierinfo_shipping_delay import SHIPPING_TYPES


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    shipping_type = fields.Selection(
        SHIPPING_TYPES, string='Sevk Türü', copy=True,
        help='Siparişin ana taşıma şekli. Beklenen yükleme tarihi bu türe göre '
             'tedarikçi fiyat listesindeki sürelerden hesaplanır.')
    expected_loading_date = fields.Datetime(
        string='Beklenen Yükleme', index=True, copy=False,
        compute='_compute_expected_loading_date',
        store=True, readonly=False)

    @api.depends('order_line.expected_loading_date')
    def _compute_expected_loading_date(self):
        """ expected_loading_date = satırlardaki en erken yükleme tarihi. """
        for order in self:
            dates_list = order.order_line.filtered(
                lambda line: not line.display_type and line.expected_loading_date
            ).mapped('expected_loading_date')
            order.expected_loading_date = min(dates_list) if dates_list else False

    @api.onchange('expected_loading_date')
    def _onchange_expected_loading_date(self):
        """Başlıktaki tarihi satırlara uygula.

        Alan bir satır değişikliğinin recompute'u sonucu değiştiyse (cascade)
        satırlara yazma; yalnızca kullanıcı başlık alanını doğrudan
        değiştirdiğinde tüm satırlara uygula. Aksi halde bir satırın yükleme
        tarihi değiştiğinde diğer satırlar ezilir.
        """
        direct_fields = self.env.context.get('direct_onchange_fields', '').split(',')
        if self.expected_loading_date and 'expected_loading_date' in direct_fields:
            self.order_line.filtered(
                lambda line: not line.display_type
            ).expected_loading_date = self.expected_loading_date

    def onchange(self, values, field_names, fields_spec):
        """ Satır editinden gelen onchange'de diğer satırların yükleme tarihini ezme.

        Satırın beklenen geliş tarihi değişip başlık tarihini yeniden
        hesapladığında standardın `onchange_date_planned`'i tüm satırların
        `date_planned`'ını günceller; bu da onların yükleme tarihlerini yanlış
        tarihten hesaplatır. Kullanıcının gerçekten dokunduğu satırların
        hesaplanan değerleri korunur, diğerlerininki sonuçtan silinir.
        """
        direct = ','.join(field_names) if isinstance(field_names, (list, tuple)) else str(field_names)
        result = super(PurchaseOrder, self.with_context(direct_onchange_fields=direct)) \
            .onchange(values, field_names, fields_spec)
        if 'order_line' in field_names and 'value' in result:
            touched = {
                cmd[1] for cmd in values.get('order_line', [])
                if isinstance(cmd, (list, tuple)) and len(cmd) > 2
                and cmd[0] == Command.UPDATE and isinstance(cmd[2], dict)
            }
            for cmd in result['value'].get('order_line', []):
                if cmd[0] == Command.UPDATE and isinstance(cmd[2], dict) \
                        and 'expected_loading_date' in cmd[2] and cmd[1] not in touched:
                    del cmd[2]['expected_loading_date']
        return result
