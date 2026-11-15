# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    quality_purchase_ok = fields.Boolean(
        string='Satınalma KK', default=False, copy=True,
        help='İşaretlendiğinde bu ürün için satınalma kalite kontrol '
             'noktası oluşturulur; gelen transfer satırı kalite '
             'kontrolü yapılmadan depoya alınamaz.')

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        templates.filtered(
            'quality_purchase_ok')._sync_purchase_quality_point()
        return templates

    def write(self, vals):
        res = super().write(vals)
        if 'quality_purchase_ok' in vals:
            self._sync_purchase_quality_point()
        return res

    def _sync_purchase_quality_point(self):
        # Keep exactly one active quality point per flagged template so
        # Odoo's standard confirmation hook creates the pending checks;
        # the warehouse user still decides which lines are *sent* to
        # quality via the row-level "KK'ya Gönder" flag.
        Point = self.env['quality.point'].with_context(active_test=False)
        incoming = self.env['stock.picking.type'].search(
            [('code', '=', 'incoming')])
        test_type = self.env['quality.point.test_type'].search(
            [('technical_name', '=', 'passfail')], limit=1)
        team = self.env['quality.alert.team'].search([], limit=1)
        fail_locs = self.env['stock.location'].search(
            [('is_failure_location', '=', True),
             ('usage', '=', 'internal')])
        for tmpl in self:
            point = Point.search(
                [('auto_purchase_tmpl_id', '=', tmpl.id)], limit=1)
            if not tmpl.quality_purchase_ok:
                if point:
                    point.active = False
                continue
            if point:
                point.write({
                    'active': True,
                    'product_ids': [
                        (6, 0, tmpl.product_variant_ids.ids)],
                    'test_type_id': point.test_type_id.id or test_type.id,
                    'team_id': point.team_id.id or team.id,
                    'measure_on': 'move_line',
                })
                point.picking_type_ids = [
                    (4, t.id)
                    for t in incoming - point.picking_type_ids]
                point.failure_location_ids = [
                    (4, l.id)
                    for l in fail_locs - point.failure_location_ids]
            else:
                Point.create({
                    'auto_purchase_tmpl_id': tmpl.id,
                    'product_ids': [
                        (6, 0, tmpl.product_variant_ids.ids)],
                    'test_type_id': test_type.id,
                    'team_id': team.id,
                    'measure_on': 'move_line',
                    'picking_type_ids': [(6, 0, incoming.ids)],
                    'failure_location_ids': [(6, 0, fail_locs.ids)],
                    'company_id': tmpl.company_id.id
                    or self.env.company.id,
                })
