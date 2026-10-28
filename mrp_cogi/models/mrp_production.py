# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools import float_is_zero


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    cogi_ids = fields.One2many('mrp.cogi.record', 'production_id',
                               string='COGI Kayıtları')
    cogi_count = fields.Integer(compute='_compute_cogi_count')

    @api.depends('cogi_ids')
    def _compute_cogi_count(self):
        for production in self:
            production.cogi_count = len(production.cogi_ids)

    def _post_inventory(self, cancel_backorder=False):
        res = super()._post_inventory(cancel_backorder=cancel_backorder)
        self._create_cogi_records()
        return res

    def _create_cogi_records(self):
        """Tamamlanan üretim emrinde reçete bileşenlerinin planlanan ve
        tüketilen miktarlarını karşılaştırır; fark için COGI kaydı açar.
        Yalnızca reçeteden gelen hareketler (bom_line_id) değerlendirilir."""
        Cogi = self.env['mrp.cogi.record']
        for production in self:
            for move in production.move_raw_ids.filtered(
                    lambda m: m.bom_line_id and m.state != 'draft'):
                product_uom = move.product_id.uom_id
                planned = move.product_uom._compute_quantity(
                    move.product_uom_qty, product_uom)
                consumed = move.product_uom._compute_quantity(
                    move.quantity, product_uom)
                missing = product_uom.round(planned - consumed)
                if float_is_zero(missing, precision_rounding=product_uom.rounding) \
                        or missing <= 0:
                    continue
                error = _(
                    'Bileşen için planlanan %(planned)s %(uom)s tüketimin '
                    '%(missing)s %(uom)s kadarı gerçekleştirilemedi.',
                    planned=planned, uom=product_uom.display_name, missing=missing)
                Cogi.create({
                    'company_id': production.company_id.id,
                    'production_id': production.id,
                    'production_name': production.name,
                    'finished_product_id': production.product_id.id,
                    'product_id': move.product_id.id,
                    'component_name': move.product_id.display_name,
                    'source_move_id': move.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'product_uom_id': product_uom.id,
                    'planned_qty': planned,
                    'consumed_qty': consumed,
                    'initial_missing_qty': missing,
                    'operator_id': self.env.user.id,
                    'error_message': error,
                    'original_error_message': error,
                })
        return True

    def action_view_cogi_records(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('mrp_cogi.mrp_cogi_record_action')
        action['domain'] = [('production_id', '=', self.id)]
        action['context'] = {'default_production_id': self.id, 'create': 0}
        if self.cogi_count == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = self.cogi_ids.id
        return action
