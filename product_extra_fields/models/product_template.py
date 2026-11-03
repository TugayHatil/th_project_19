# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    old_default_code = fields.Char(string='Eski Malzeme No')
    material_group_id = fields.Many2one(
        'product.material.group', string='Mal Grubu',
        index=True, ondelete='restrict')
    external_material_group_id = fields.Many2one(
        'product.external.material.group', string='Harici Mal Grubu',
        index=True, ondelete='restrict')
    validity_start_date = fields.Date(string='Geçerlilik Başlangıç')
    mip_no = fields.Many2one(
        'mip.definition', string='MİP No', index=True, ondelete='restrict')
    mip_responsible = fields.Char(
        string='MİP Sorumlusu',
        related='mip_no.responsible', store=True, readonly=True)
    production_supervisor_no = fields.Many2one(
        'production.supervisor', string='Üretim Sorumlusu No',
        index=True, ondelete='restrict')
    production_supervisor = fields.Char(
        string='Üretim Sorumlusu',
        related='production_supervisor_no.responsible',
        store=True, readonly=True)
    production_storage_location = fields.Many2one(
        'stock.location', string='Üretim Depo Yeri',
        domain="[('usage', '=', 'internal')]", index=True, ondelete='restrict')
    external_procurement_storage_location = fields.Many2one(
        'stock.location', string='Dışarıdan Tedarik Depo Yeri',
        domain="[('usage', '=', 'internal')]", index=True, ondelete='restrict')
    quality_inspection_production = fields.Boolean(
        string='Üretim KK', default=False)
    quality_inspection_purchase = fields.Boolean(
        string='Satınalma KK', default=False)
    purchase_order_qty_rounding = fields.Float(string='Satınalma Katları')
    purchase_group = fields.Selection(
        [('direct', 'Direkt'), ('indirect', 'Endirekt')],
        string='Satınalma Grubu')

    @api.constrains('purchase_order_qty_rounding')
    def _check_purchase_order_qty_rounding(self):
        for product in self:
            if product.purchase_order_qty_rounding < 0:
                raise ValidationError(_('Satınalma katları negatif olamaz.'))
