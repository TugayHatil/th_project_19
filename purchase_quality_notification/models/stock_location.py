# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockLocation(models.Model):
    _inherit = 'stock.location'

    is_failure_location = fields.Boolean(
        string='Arıza Konumu mu?', default=False, copy=False)

    @api.constrains('is_failure_location', 'usage')
    def _check_is_failure_location_usage(self):
        for location in self:
            if location.is_failure_location and location.usage != 'internal':
                raise ValidationError(_(
                    'Arıza konumu yalnızca dahili stok konumları için '
                    'işaretlenebilir.'))
