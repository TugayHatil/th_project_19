# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sale_type = fields.Selection([
        ('domestic', 'Yurtiçi Satış'),
        ('export', 'Yurtdışı Satış'),
        ('tender', 'İhale'),
        ('free', 'Bedelsiz'),
        ('other', 'Diğer'),
    ], string='Satış Türü', tracking=True)
    tender_id = fields.Many2one(
        'sale.tender', string='İhale', index=True, check_company=True)

    @api.constrains('sale_type', 'tender_id')
    def _check_tender_required(self):
        for order in self:
            if order.sale_type == 'tender' and not order.tender_id:
                raise ValidationError(_(
                    'Satış türü "İhale" olan tekliflerde İhale alanı '
                    'zorunludur.'))
            if order.tender_id and order.partner_id \
                    and order.tender_id.partner_id != order.partner_id:
                raise ValidationError(_(
                    'Seçilen ihale (%(tender)s), teklif müşterisiyle '
                    'eşleşmiyor. Yalnızca %(partner)s müşterisine ait '
                    'ihaleler seçilebilir.',
                    tender=order.tender_id.display_name,
                    partner=order.partner_id.display_name))

    @api.onchange('tender_id')
    def _onchange_tender_id(self):
        if self.tender_id:
            self.sale_type = 'tender'
            if not self.partner_id:
                self.partner_id = self.tender_id.partner_id

    @api.onchange('partner_id')
    def _onchange_partner_id_tender(self):
        if self.tender_id and self.partner_id \
                and self.tender_id.partner_id != self.partner_id:
            self.tender_id = False
