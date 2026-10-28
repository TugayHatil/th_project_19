# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MrpCogiCloseWizard(models.TransientModel):
    _name = 'mrp.cogi.close.wizard'
    _description = 'COGI Düzeltmeden Kapatma Sihirbazı'

    cogi_record_id = fields.Many2one('mrp.cogi.record', required=True, readonly=True)
    close_reason = fields.Selection([
        ('planning', 'Planlama hatası'),
        ('duplicate', 'Mükerrer kayıt'),
        ('mo_cancel', 'Üretim iptali nedeniyle gereksiz hareket'),
        ('no_consumption', 'Gerçekleşmeyen tüketim'),
        ('master_data', 'Yanlış ana veri'),
        ('other', 'Diğer'),
    ], string='Kapatma Nedeni', required=True)
    close_note = fields.Text('Kapatma Açıklaması')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res['cogi_record_id'] = self.env.context.get('active_id')
        return res

    def action_close(self):
        self.ensure_one()
        if self.close_reason == 'other' and not self.close_note:
            raise UserError(_('"Diğer" kapatma nedeni seçildiğinde açıklama zorunludur.'))
        self.cogi_record_id._close_without_correction(self.close_reason, self.close_note)
        return {'type': 'ir.actions.act_window_close'}
