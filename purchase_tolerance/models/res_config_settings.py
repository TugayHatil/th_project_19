# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    purchase_tolerance = fields.Float(
        string='Varsayılan Satınalma Toleransı (%)',
        digits='Discount',
        config_parameter='purchase_tolerance.default_purchase_tolerance',
        help="Ürün veya satınalma siparişi satırında özel tolerans tanımlanmadığında "
             "kullanılan varsayılan fazla teslimat toleransı.",
    )
    tolerance_excess_location_id = fields.Many2one(
        'stock.location',
        string='Tolerans Dışı Miktar Konumu',
        compute='_compute_tolerance_excess_location_id',
        inverse='_inverse_tolerance_excess_location_id',
        domain="[('usage', '=', 'internal')]",
        check_company=True,
        help="Koşullu onaylanan tolerans taleplerinde, onaylanan miktarın "
             "üzerinde kalan tolerans dışı miktarın mal kabulde yönlendirileceği "
             "konum. Bu konumdan tedarikçiye otomatik iade transferi oluşturulur.",
    )

    def _get_excess_location_param(self):
        """ir.config_parameter'daki konum id'sini döner; geçersiz/boş
        değerlerde (ör. alan temizlendiğinde 'False' string'i) None döner."""
        param = self.env['ir.config_parameter'].sudo().get_param(
            'purchase_tolerance.excess_location_id')
        try:
            return int(param) if param else None
        except (TypeError, ValueError):
            return None

    def _compute_tolerance_excess_location_id(self):
        location_id = self._get_excess_location_param() or False
        for settings in self:
            settings.tolerance_excess_location_id = location_id

    def _inverse_tolerance_excess_location_id(self):
        for settings in self:
            self.env['ir.config_parameter'].sudo().set_param(
                'purchase_tolerance.excess_location_id',
                settings.tolerance_excess_location_id.id or False)
