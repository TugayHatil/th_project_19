# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class PurchaseRequestLine(models.Model):
    _inherit = 'purchase.request.line'

    def action_open_line_paste_wizard(self):
        # x2many <control> butonları satır modelinde çağrılır; talep id'si
        # buton context'i ile gelir
        request = self.env['purchase.request'].browse(
            self.env.context.get('request_id'))
        request.ensure_one()
        if not request.is_editable:
            raise UserError(_(
                'Satır yapıştırma yalnızca düzenlenebilir (taslak) '
                'taleplerde kullanılabilir.'))
        return {
            'name': _('Satır Yapıştır'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.request.line.paste.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': request.id},
        }
