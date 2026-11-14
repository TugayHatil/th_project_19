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

    @api.model_create_multi
    def create(self, vals_list):
        locations = super().create(vals_list)
        if any(vals.get('is_failure_location') for vals in vals_list):
            locations._resync_auto_quality_point_failure_locations()
        return locations

    def write(self, vals):
        res = super().write(vals)
        if {'is_failure_location', 'usage', 'company_id', 'active'} & vals.keys():
            self._resync_auto_quality_point_failure_locations()
        return res

    def _resync_auto_quality_point_failure_locations(self):
        points = self.env['quality.point'].with_context(active_test=False).sudo().search(
            [('auto_purchase_tmpl_id', '!=', False)])
        for point in points:
            locations = self.env['stock.location'].sudo().search([
                ('is_failure_location', '=', True),
                ('active', '=', True),
                ('company_id', 'in', [point.company_id.id, False]),
            ])
            if point.failure_location_ids != locations:
                point.failure_location_ids = [(6, 0, locations.ids)]
