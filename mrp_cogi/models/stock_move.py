# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    cogi_record_id = fields.Many2one('mrp.cogi.record', string='COGI Kaydı',
                                     readonly=True, index=True, copy=False,
                                     ondelete='set null')
    cogi_source_move_id = fields.Many2one(
        'stock.move', string='COGI Kaynak Hareketi', readonly=True, index=True,
        copy=False, ondelete='set null',
        help="Bu düzeltme hareketinin istinaden oluşturulduğu asıl bileşen hareketi.")
    source_cogi_ids = fields.One2many('mrp.cogi.record', 'source_move_id',
                                      string='Kaynak Olunan COGI Kayıtları')
    cogi_correction_move_ids = fields.One2many(
        'stock.move', 'cogi_source_move_id', string='COGI Düzeltme Hareketleri')
    cogi_source_names = fields.Char(compute='_compute_cogi_source_names',
                                    string='COGI Kaydı')

    @api.depends('source_cogi_ids', 'source_cogi_ids.name')
    def _compute_cogi_source_names(self):
        for move in self:
            move.cogi_source_names = ', '.join(move.source_cogi_ids.mapped('name'))

    def action_view_source_cogi(self):
        self.ensure_one()
        cogi = self.source_cogi_ids[:1]
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.cogi.record',
            'res_id': cogi.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }
