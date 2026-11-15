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

    def write(self, vals):
        res = super().write(vals)
        if 'is_failure_location' in vals:
            self._sync_failure_locations_to_points()
        return res

    def _sync_failure_locations_to_points(self):
        # The standard check's failure dialog offers the locations listed
        # on its quality point — keep the auto purchase points in sync
        # with the locations flagged as failure locations.
        locs = self.env['stock.location'].search(
            [('is_failure_location', '=', True),
             ('usage', '=', 'internal')])
        points = self.env['quality.point'].with_context(
            active_test=False).search(
                [('auto_purchase_tmpl_id', '!=', False)])
        points.failure_location_ids = [(6, 0, locs.ids)]
