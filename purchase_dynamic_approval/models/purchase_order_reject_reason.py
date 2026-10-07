# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrderRejectReason(models.Model):
    _name = 'purchase.order.reject.reason'
    _description = 'Purchase Order Reject Reason'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sıra', default=10)
    name = fields.Char(string='Red Nedeni', required=True, translate=True)
    active = fields.Boolean(string='Aktif', default=True)
