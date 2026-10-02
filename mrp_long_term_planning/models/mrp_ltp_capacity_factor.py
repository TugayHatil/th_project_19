# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpLtpCapacityFactor(models.Model):
    """Monthly capacity override per workcenter (BRD §2/§15).

    factor == 1.0 means "use the standard capacity" — setting the factor
    back to 1.0 deletes the record instead of storing a no-op row. The
    workcenter master data (calendar, capacity lines) is never touched.
    """

    _name = "mrp.ltp.capacity.factor"
    _description = "Monthly Capacity Factor"
    _order = "workcenter_id, period"

    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="Work Center", required=True, index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company,
    )
    year = fields.Integer(required=True)
    month = fields.Integer(required=True)
    # YYYYMM — monotonic key used for window filtering.
    period = fields.Integer(compute="_compute_period", store=True, index=True)
    factor = fields.Float(
        string="Capacity Factor", digits=(16, 2), default=1.0,
    )

    _sql_constraints = [
        ("check_month", "CHECK(month BETWEEN 1 AND 12)",
         "Month must be between 1 and 12."),
        ("check_factor", "CHECK(factor > 0)",
         "The capacity factor must be greater than zero."),
    ]

    @api.depends("year", "month")
    def _compute_period(self):
        for line in self:
            line.period = line.year * 100 + line.month

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mrp_ltp_cap_factor_uniq
            ON mrp_ltp_capacity_factor (company_id, workcenter_id, period)
        """)
