# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpLtpRevision(models.Model):
    """Immutable baseline of a "Planlamayı Teyit Et" action (BRD §6/§18).

    A revision is a historical snapshot: once created it is never updated.
    Access rules only grant read — lines are created through sudo() by
    confirm_plan, so users can never edit a stored baseline.
    """

    _name = "mrp.ltp.revision"
    _description = "Long-Term Planning Baseline Revision"
    _order = "id desc"

    name = fields.Char(readonly=True, index=True)
    confirm_date = fields.Datetime(
        readonly=True, default=fields.Datetime.now, required=True)
    user_id = fields.Many2one(
        "res.users", readonly=True, required=True,
        default=lambda self: self.env.user)
    company_id = fields.Many2one(
        "res.company", readonly=True, required=True, index=True,
        default=lambda self: self.env.company)
    # Same scoping rule as mrp.ltp.line: empty = "all warehouses" plan.
    warehouse_id = fields.Many2one(
        "stock.warehouse", readonly=True, index=True)
    # YYYYMM of the first month of the 12-month window at confirm time.
    period_start = fields.Integer(readonly=True, required=True)
    line_ids = fields.One2many(
        "mrp.ltp.revision.line", "revision_id", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        revisions = super().create(vals_list)
        for revision in revisions:
            if not revision.name:
                revision.name = "#%s" % revision.id
        return revisions


class MrpLtpRevisionLine(models.Model):
    """Per product+month snapshot row of a baseline (BRD §7)."""

    _name = "mrp.ltp.revision.line"
    _description = "Long-Term Planning Baseline Revision Line"
    _order = "product_id, period"

    revision_id = fields.Many2one(
        "mrp.ltp.revision", required=True, index=True, ondelete="cascade")
    product_id = fields.Many2one(
        "product.product", required=True, index=True, ondelete="cascade")
    year = fields.Integer(required=True)
    month = fields.Integer(required=True)
    period = fields.Integer(compute="_compute_period", store=True, index=True)
    order_qty = fields.Float(
        string="Confirmed Order Qty", digits="Long-Term Planning Quantity",
        default=0.0)
    forecast_qty = fields.Float(
        string="Confirmed Forecast Qty", digits="Long-Term Planning Quantity",
        default=0.0)
    demand_qty = fields.Float(
        string="Confirmed Total Demand", digits="Long-Term Planning Quantity",
        default=0.0)
    planned_qty = fields.Float(
        string="Confirmed Planned Qty", digits="Long-Term Planning Quantity",
        default=0.0)

    @api.depends("year", "month")
    def _compute_period(self):
        for line in self:
            line.period = line.year * 100 + line.month
