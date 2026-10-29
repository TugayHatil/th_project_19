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
    cogi_state = fields.Selection([
        ('open', 'Açık'),
        ('reprocessing', 'Yeniden İşleniyor'),
        ('done', 'Başarılı'),
        ('closed', 'Düzeltmeden Kapatıldı'),
    ], compute='_compute_cogi_state', string='COGI Durumu')

    @api.depends('source_cogi_ids', 'source_cogi_ids.name')
    def _compute_cogi_source_names(self):
        for move in self:
            move.cogi_source_names = ', '.join(move.source_cogi_ids.mapped('name'))

    @api.depends('source_cogi_ids', 'source_cogi_ids.state')
    def _compute_cogi_state(self):
        for move in self:
            states = move.source_cogi_ids.mapped('state')
            if any(s in ('open', 'reprocessing') for s in states):
                move.cogi_state = 'open'
            elif states and all(s == 'closed' for s in states):
                move.cogi_state = 'closed'
            elif states:
                move.cogi_state = 'done'
            else:
                move.cogi_state = False

    def action_view_source_cogi(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'mrp_cogi.mrp_cogi_record_action')
        action['domain'] = [('source_move_id', '=', self.id)]
        action['context'] = {'create': 0}
        if len(self.source_cogi_ids) == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = self.source_cogi_ids.id
        return action
