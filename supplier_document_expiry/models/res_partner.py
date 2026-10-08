# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    supplier_document_ids = fields.One2many(
        'supplier.document', 'partner_id', string='Tedarikçi Belgeleri')
    supplier_document_count = fields.Integer(
        string='Belge Sayısı', compute='_compute_supplier_document_count')

    def _compute_supplier_document_count(self):
        counts = dict(self.env['supplier.document']._read_group(
            [('partner_id', 'in', self.ids)],
            groupby=['partner_id'], aggregates=['__count']))
        for partner in self:
            partner.supplier_document_count = counts.get(partner, 0)
