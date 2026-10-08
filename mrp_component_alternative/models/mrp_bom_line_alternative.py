# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MrpBomLineAlternative(models.Model):
    _name = "mrp.bom.line.alternative"
    _description = "BOM Component Alternative"
    _order = "sequence, id"

    bom_line_id = fields.Many2one(
        "mrp.bom.line", string="Component Line",
        required=True, ondelete="cascade", index=True)
    bom_id = fields.Many2one(
        "mrp.bom", related="bom_line_id.bom_id",
        store=True, index=True, readonly=True)
    product_id = fields.Many2one(
        "product.product", string="Main Component",
        related="bom_line_id.product_id", store=True, readonly=True)
    alternative_product_id = fields.Many2one(
        "product.product", string="Alternative Product",
        required=True, ondelete="restrict")
    sequence = fields.Integer(string="Priority", default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", related="bom_line_id.company_id",
        store=True, readonly=True)

    _bom_line_alt_unique = models.Constraint(
        "unique(bom_line_id, alternative_product_id)",
        "The same alternative can only be defined once per component line.")

    @api.constrains("bom_line_id", "alternative_product_id")
    def _check_alternative_product(self):
        for alternative in self:
            if alternative.alternative_product_id == alternative.product_id:
                raise ValidationError(_(
                    "The alternative product cannot be the same as the "
                    "main component (%s).", alternative.product_id.display_name))
            main_uom = alternative.product_id.uom_id
            alt_uom = alternative.alternative_product_id.uom_id
            if not main_uom._has_common_reference(alt_uom):
                raise ValidationError(_(
                    "The alternative product %(alt)s uses a different unit of "
                    "measure category than the main component %(main)s.",
                    alt=alternative.alternative_product_id.display_name,
                    main=alternative.product_id.display_name))
