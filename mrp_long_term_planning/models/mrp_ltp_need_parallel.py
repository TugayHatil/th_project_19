# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpLtpNeedParallel(models.Model):
    """Planner-chosen parallel capacity for one production need.

    How many machines run the need's operations concurrently — op
    hours divide by it (capacity 2 turns a 20h job into a 10h window).
    Lives apart from mrp.ltp.need.schedule so unconfirmed needs can
    carry the choice too; a confirmed schedule's own capacity wins.
    """

    _name = "mrp.ltp.need.parallel"
    _description = "Need-Level Parallel Capacity"
    _check_company_auto = True

    product_id = fields.Many2one(
        "product.product", required=True, index=True, ondelete="cascade")
    line_key = fields.Char(required=True, index=True)
    warehouse_id = fields.Many2one("stock.warehouse", index=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company)
    capacity = fields.Integer(
        "Parallel Capacity", default=1, required=True)

    def init(self):
        self.env.cr.execute("""
            DROP INDEX IF EXISTS mrp_ltp_need_parallel_uniq;
            CREATE UNIQUE INDEX IF NOT EXISTS mrp_ltp_need_parallel_uniq
            ON mrp_ltp_need_parallel
               (company_id, product_id, COALESCE(warehouse_id, 0), line_key)
        """)

    @api.constrains("capacity")
    def _check_capacity(self):
        for rec in self:
            if rec.capacity < 1:
                raise models.ValidationError(
                    "Parallel capacity must be a positive integer.")
