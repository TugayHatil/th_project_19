# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SupplierDocumentType(models.Model):
    _name = 'supplier.document.type'
    _description = 'Tedarikçi Belge Türü'
    _order = 'sequence, name, id'

    sequence = fields.Integer(string='Sıra', default=10)
    name = fields.Char(string='Belge Türü', required=True, translate=True)
    warning_days_yellow = fields.Integer(
        string='Sarı Uyarı Günü', required=True, default=30,
        help='Kalan gün sayısı bu değere eşit veya küçükse (turuncu '
             'eşiğin üzerinde) belge sarı duruma geçer.')
    warning_days_orange = fields.Integer(
        string='Turuncu Uyarı Günü', required=True, default=7,
        help='Kalan gün sayısı bu değere eşit veya küçükse (ve '
             'pozitifse) belge turuncu duruma geçer.')
    active = fields.Boolean(string='Aktif', default=True)

    @api.constrains('warning_days_yellow', 'warning_days_orange')
    def _check_warning_days(self):
        for doc_type in self:
            if (doc_type.warning_days_yellow < 0
                    or doc_type.warning_days_orange < 0):
                raise ValidationError(_(
                    'Uyarı gün değerleri negatif olamaz.'))
            if doc_type.warning_days_yellow <= doc_type.warning_days_orange:
                raise ValidationError(_(
                    '"Sarı Uyarı Günü", "Turuncu Uyarı Günü" değerinden '
                    'büyük olmalıdır.'))
