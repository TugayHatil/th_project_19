# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    tender_id = fields.Many2one(
        'sale.tender', string='İhale', index=True, check_company=True)
    # View'larda "Satış Türü = İhale" koşulu için yardımcı alan
    is_tender_type = fields.Boolean(compute='_compute_is_tender_type')

    @api.depends('so_type_id')
    def _compute_is_tender_type(self):
        tender_type = self._get_tender_order_type()
        for order in self:
            order.is_tender_type = bool(
                tender_type) and order.so_type_id == tender_type

    def _get_tender_order_type(self):
        return self.env.ref(
            'sale_tender.sale_order_type_tender', raise_if_not_found=False)

    @api.constrains('so_type_id', 'tender_id', 'partner_id')
    def _check_tender_required(self):
        tender_type = self._get_tender_order_type()
        for order in self:
            if tender_type and order.so_type_id == tender_type \
                    and not order.tender_id:
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
            tender_type = self._get_tender_order_type()
            if tender_type:
                self.so_type_id = tender_type
            if not self.partner_id:
                self.partner_id = self.tender_id.partner_id

    @api.onchange('partner_id')
    def _onchange_partner_id_tender(self):
        if self.tender_id and self.partner_id \
                and self.tender_id.partner_id != self.partner_id:
            self.tender_id = False
