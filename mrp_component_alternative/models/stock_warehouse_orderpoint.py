# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    has_bom_alternatives = fields.Boolean(
        compute="_compute_has_bom_alternatives", compute_sudo=True)

    @api.depends("product_id", "company_id")
    def _compute_has_bom_alternatives(self):
        grouped = self.env["mrp.bom.line.alternative"]._read_group(
            [("product_id", "in", self.product_id.ids),
             ("active", "=", True)],
            ["product_id", "company_id"], ["__count"])
        alt_companies = {}
        for product, company, _count in grouped:
            alt_companies.setdefault(product.id, set()).add(
                company.id if company else False)
        for orderpoint in self:
            companies = alt_companies.get(orderpoint.product_id.id, set())
            orderpoint.has_bom_alternatives = (
                False in companies or orderpoint.company_id.id in companies)

    def action_view_alternatives(self):
        self.ensure_one()
        return self.env["mrp.alternative.selector"]._open_for_orderpoint(self)
