# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SaleTender(models.Model):
    _name = 'sale.tender'
    _description = 'İhale'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tender_date desc, id desc'
    _check_company_auto = True
    _rec_names_search = ['tender_no', 'name']

    display_name = fields.Char(compute='_compute_display_name')
    tender_no = fields.Char(
        string='İhale Numarası', required=True, index=True, tracking=True,
        help="Müşteri veya ihale kurumu tarafından verilen ihale numarası.")
    name = fields.Char(string='İhale Adı', required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Müşteri', required=True, index=True,
        tracking=True, check_company=True)
    tender_date = fields.Date(string='İhale Tarihi', tracking=True)
    bid_deadline = fields.Datetime(string='Son Teklif Tarihi', tracking=True)
    state = fields.Selection([
        ('draft', 'Hazırlık'),
        ('bid_submitted', 'Teklif Verildi'),
        ('won', 'Kazanıldı'),
        ('lost', 'Kaybedildi'),
        ('cancel', 'İptal'),
    ], string='Durum', default='draft', required=True, tracking=True,
        copy=False)
    user_id = fields.Many2one(
        'res.users', string='Sorumlu', index=True, tracking=True,
        default=lambda self: self.env.user)
    competitor_ids = fields.Many2many(
        'sale.tender.competitor', 'sale_tender_competitor_rel', 'tender_id',
        'competitor_id', string='Rakipler')
    lost_reason_id = fields.Many2one(
        'sale.tender.lost.reason', string='Kayıt Nedeni', tracking=True,
        ondelete='restrict', copy=False)
    description = fields.Text(string='Açıklama')
    company_id = fields.Many2one(
        'res.company', string='Şirket', required=True, index=True,
        default=lambda self: self.env.company)
    active = fields.Boolean(string='Aktif', default=True)
    sale_order_ids = fields.One2many(
        'sale.order', 'tender_id', string='Teklifler')
    sale_order_count = fields.Integer(
        string='Teklif Sayısı', compute='_compute_sale_order_count')

    @api.depends('tender_no', 'name')
    def _compute_display_name(self):
        for tender in self:
            tender.display_name = ' - '.join(
                part for part in (tender.tender_no, tender.name) if part)

    @api.depends('sale_order_ids')
    def _compute_sale_order_count(self):
        # İptal edilmiş eski revizyonlar (active=False) da sayılmalı
        orders = self.env['sale.order'].with_context(active_test=False)
        for tender in self:
            tender.sale_order_count = orders.search_count(
                [('tender_id', '=', tender.id)])

    @api.constrains('state', 'lost_reason_id')
    def _check_lost_reason(self):
        for tender in self:
            if tender.state == 'lost' and not tender.lost_reason_id:
                raise ValidationError(_(
                    '"Kaybedildi" durumu için kayıt nedeni seçilmelidir.'))

    def write(self, vals):
        # Kaybedildi'den çıkıldığında kayıt nedenini temizle
        if vals.get('state') and vals['state'] != 'lost':
            vals.setdefault('lost_reason_id', False)
        return super().write(vals)

    def action_set_lost(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Kayıt Nedeni'),
            'res_model': 'sale.tender.lost.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_tender_id': self.id},
        }

    def unlink(self):
        linked = self.env['sale.order'].with_context(
            active_test=False).search([('tender_id', 'in', self.ids)])
        if linked:
            raise UserError(_(
                'Bağlı satış teklifi bulunan ihale kayıtları silinemez: %s',
                ', '.join((self & linked.mapped('tender_id')).mapped(
                    'display_name'))))
        return super().unlink()

    def action_cancel_tender(self):
        self.write({'state': 'cancel'})

    def _get_tender_order_type(self):
        return self.env.ref(
            'sale_tender.sale_order_type_tender', raise_if_not_found=False)

    def _get_quotation_context(self):
        tender_type = self._get_tender_order_type()
        return {
            'default_partner_id': self.partner_id.id,
            'default_so_type_id': tender_type.id if tender_type else False,
            'default_tender_id': self.id,
            'default_user_id': self.user_id.id,
        }

    def action_create_quotation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Yeni Teklif'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'target': 'current',
            'context': self._get_quotation_context(),
        }

    def action_view_quotations(self):
        self.ensure_one()
        list_view = self.env.ref('sale_tender.sale_tender_order_list')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Teklifler'),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'views': [(list_view.id, 'list'), (False, 'form')],
            'domain': [('tender_id', '=', self.id)],
            # İptal edilmiş eski revizyonlar da listelenebilmeli
            'context': dict(self._get_quotation_context(), active_test=False),
        }
