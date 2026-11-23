# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductManufacturer(models.Model):
    _name = 'product.manufacturer'
    _description = 'Ürün Üreticisi'
    _order = 'product_id, manufacturer_id, manufacturer_code'

    product_id = fields.Many2one(
        'product.product',
        string='Ürün',
        required=True,
        ondelete='cascade',
    )
    manufacturer_code = fields.Char(
        string='Üretici Kodu',
        required=True,
    )
    manufacturer_id = fields.Many2one(
        'res.partner',
        string='Üretici',
        required=True,
        domain="[('is_manufacturer', '=', True)]",
        context={'default_is_manufacturer': True},
    )
    note = fields.Char(
        string='Not',
    )
    state = fields.Selection(
        [
            ('not_for_new_design', 'Yeni Tasarım İçin Uygun Değil'),
            ('recommended_for_new_design', 'Yeni Tasarım İçin Önerilen'),
            ('released_to_production', 'Seri Üretime Uygun'),
            ('prototype', 'Prototip'),
        ],
        string='Durumu',
        required=True,
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'product_manufacturer_attachment_rel',
        'manufacturer_row_id',
        'attachment_id',
        string='Dokümanlar',
    )

    _product_manufacturer_code_unique = models.Constraint(
        'unique(product_id, manufacturer_id, manufacturer_code)',
        'Aynı ürün, üretici ve üretici kodu kombinasyonu daha önce tanımlanmıştır.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_document_attachments()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'attachment_ids' in vals:
            self._sync_document_attachments()
        return res

    def _sync_document_attachments(self):
        """Satır kaydedilmeden önce yüklenen eklerin res_model/res_id
        bilgisini üretici satırına bağlar; böylece standart attachment
        erişim kontrolü satır yetkileri üzerinden çalışır."""
        for rec in self:
            misplaced = rec.attachment_ids.filtered(
                lambda a: a.res_model != 'product.manufacturer'
                or a.res_id != rec.id)
            if misplaced:
                misplaced.sudo().write({
                    'res_model': 'product.manufacturer',
                    'res_id': rec.id,
                })
