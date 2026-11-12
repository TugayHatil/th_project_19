# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class PurchaseRequest(models.Model):
    _inherit = 'purchase.request'

    def action_open_line_paste_wizard(self):
        self.ensure_one()
        if not self.is_editable:
            raise UserError(_(
                'Satır yapıştırma yalnızca düzenlenebilir (taslak) '
                'taleplerde kullanılabilir.'))
        return {
            'name': _('Satır Yapıştır'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.request.line.paste.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }
