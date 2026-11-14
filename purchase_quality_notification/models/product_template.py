# -*- coding: utf-8 -*-
from odoo import api, fields, models


QUALITY_POINT_NOTE = (
    "Tedarikçiden gelen bileşenlerin kalite ve uygunluk kontrollerini "
    "gerçekleştirin. Uygun olmayan ürünleri belirleyerek tanımlı arıza "
    "lokasyonuna ayırın. Kontrol sonucunu Geçti veya Kaldı olarak kaydedin."
)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    quality_purchase_ok = fields.Boolean(
        string='Satınalma KK', default=False, copy=True,
        help='İşaretlendiğinde bu ürün için otomatik kalite kontrol noktası '
             'oluşturulur ve gelen transferler kalite ekibine bildirilebilir.')

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        templates.filtered('quality_purchase_ok')._sync_purchase_quality_point()
        return templates

    def write(self, vals):
        res = super().write(vals)
        if 'quality_purchase_ok' in vals or 'active' in vals:
            self._sync_purchase_quality_point()
        return res

    def unlink(self):
        auto_point_ids = self.env['quality.point'].with_context(
            active_test=False).sudo().search(
                [('auto_purchase_tmpl_id', 'in', self.ids)]).ids
        res = super().unlink()
        if res and auto_point_ids:
            self.env['quality.point'].sudo().browse(auto_point_ids).write(
                {'active': False})
        return res

    def _sync_purchase_quality_point(self):
        Point = self.env['quality.point'].with_context(active_test=False).sudo()
        for tmpl in self:
            point = Point.search(
                [('auto_purchase_tmpl_id', '=', tmpl.id)], limit=1)
            if tmpl.quality_purchase_ok and tmpl.active:
                vals = tmpl._prepare_purchase_quality_point_vals()
                if point:
                    point.write({
                        'active': True,
                        'product_ids': vals['product_ids'],
                        'picking_type_ids': vals['picking_type_ids'],
                        'failure_location_ids': vals['failure_location_ids'],
                        'team_id': vals['team_id'],
                    })
                else:
                    Point.create(vals)
            elif point.active:
                point.active = False

    def _prepare_purchase_quality_point_vals(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        incoming_types = self.env['stock.picking.type'].sudo().search([
            ('code', '=', 'incoming'),
            ('company_id', '=', company.id),
        ])
        team = self.env['quality.alert.team'].sudo().search(
            [('name', '=', 'Main Quality Team'),
             ('company_id', 'in', [company.id, False])], limit=1)
        if not team:
            team = self.env['quality.alert.team'].sudo().search(
                [('company_id', 'in', [company.id, False])], limit=1)
        if not team:
            team = self.env['quality.alert.team'].sudo().create({
                'name': 'Main Quality Team',
                'company_id': company.id,
            })
        test_type = self.env['quality.point.test_type'].sudo().search(
            [('technical_name', '=', 'passfail')], limit=1)
        failure_locations = self.env['stock.location'].sudo().search([
            ('is_failure_location', '=', True),
            ('active', '=', True),
            ('company_id', 'in', [company.id, False]),
        ])
        return {
            'title': 'Bileşenler',
            'product_ids': [(6, 0, self.product_variant_ids.ids)],
            'picking_type_ids': [(6, 0, incoming_types.ids)],
            'company_id': company.id,
            'measure_on': 'move_line',
            'measure_frequency_type': 'all',
            'testing_percentage_within_lot': 100.0,
            'test_type_id': test_type.id,
            'team_id': team.id,
            'failure_location_ids': [(6, 0, failure_locations.ids)],
            'note': QUALITY_POINT_NOTE,
            'auto_purchase_tmpl_id': self.id,
        }
