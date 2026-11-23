# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.fields import Domain


class ProductProduct(models.Model):
    _inherit = 'product.product'

    manufacturer_ids = fields.One2many(
        'product.manufacturer',
        'product_id',
        string='Üreticiler',
    )

    @api.model
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        # display_name tabanlı aramalara (m2o filtreleri, varyant
        # birleşimi vb.) üretici kodu (MPN) de dahil olsun
        if value and operator not in Domain.NEGATIVE_OPERATORS:
            domain = Domain(domain) | Domain(
                'manufacturer_ids.manufacturer_code', operator, value)
        return domain

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        results = super().name_search(
            name=name, domain=domain, operator=operator, limit=limit)
        # Ürün eşleşmelerinden sonra ikinci öncelik: üretici kodu (MPN)
        if name and operator not in Domain.NEGATIVE_OPERATORS:
            limit_rest = limit and limit - len(results)
            if limit_rest is None or limit_rest > 0:
                mpn_domain = (
                    Domain(domain or Domain.TRUE)
                    & Domain('id', 'not in', [res_id for res_id, _ in results])
                    & Domain(
                        'manufacturer_ids.manufacturer_code', operator, name)
                )
                extra = self.search_fetch(
                    mpn_domain, ['display_name'], limit=limit_rest)
                results += [(p.id, p.display_name) for p in extra.sudo()]
        return results
