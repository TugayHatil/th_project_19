# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrderCancelReason(models.Model):
    _name = 'purchase.order.cancel.reason'
    _description = 'Purchase Order Cancel Reason'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sıra', default=10)
    name = fields.Char(string='İptal Nedeni', required=True, translate=True)
    active = fields.Boolean(string='Aktif', default=True)
    is_other = fields.Boolean(
        string='Diğer',
        help='İşaretlenirse bu neden seçildiğinde açıklama girilmesi '
             'zorunludur ve iptal analizinde "Diğer" filtresiyle ayrıca '
             'izlenebilir.')
