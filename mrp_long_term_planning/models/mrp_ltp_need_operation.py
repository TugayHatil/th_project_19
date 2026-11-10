# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MrpLtpNeedOperation(models.Model):
    """One APS-planned operation of a production need.

    Rows are created as a draft by the auto-plan engine and confirmed
    by the planner — only confirmed rows reserve workcenter capacity.
    The need is identified the same way mrp.ltp.need.schedule does it
    (product_id + line_key + warehouse), so an operation plan always
    maps back to its source order line / MİP record. ``predecessor_id``
    keeps the BoM operation order inside one need.
    """

    _name = "mrp.ltp.need.operation"
    _description = "APS Operation Plan Row"
    _order = "planned_start, sequence, id"
    _check_company_auto = True

    product_id = fields.Many2one(
        "product.product", string="Product", required=True, index=True,
        ondelete="cascade")
    # need identity — the MİP plan key ("mv:…"/"bom:…"/"im:…")
    line_key = fields.Char(required=True, index=True)
    warehouse_id = fields.Many2one(
        "stock.warehouse", string="Warehouse", index=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company)

    bom_id = fields.Many2one("mrp.bom", string="BoM")
    operation_id = fields.Many2one(
        "mrp.routing.workorder", string="BoM Operation")
    name = fields.Char(string="Operation", required=True)
    sequence = fields.Integer(default=10)
    predecessor_id = fields.Many2one(
        "mrp.ltp.need.operation", string="Previous Operation",
        ondelete="set null")
    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="Work Center", index=True)

    qty = fields.Float("Planned Quantity",
                       digits="Long-Term Planning Quantity")
    unit_hours = fields.Float("Unit Hours", digits=(16, 4))
    total_hours = fields.Float("Operation Hours", digits=(16, 2))
    planned_start = fields.Datetime("Planned Start", index=True)
    planned_end = fields.Datetime("Planned End", index=True)
    locked = fields.Boolean(
        "Locked", default=False,
        help="Locked operations are kept untouched by re-planning.")

    state = fields.Selection([
        ("draft", "Draft"),
        ("shortage", "Capacity Shortage"),
        ("confirmed", "Confirmed"),
        ("done", "Done"),
    ], default="draft", index=True)

    _sql_constraints = [(
        "check_dates",
        "CHECK(planned_end IS NULL OR planned_start IS NULL"
        "     OR planned_end >= planned_start)",
        "Operation end cannot be earlier than its start."),
    ]

    # a confirmed op plan feeds the MİP plan's component need dates —
    # every change must invalidate the cached plan
    def _bump_mip_plan_version(self):
        if "mrp.purchase.need" in self.env:
            self.env["mrp.purchase.need"]._bump_plan_version()

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._bump_mip_plan_version()
        return recs

    def write(self, vals):
        res = super().write(vals)
        self._bump_mip_plan_version()
        return res

    def unlink(self):
        res = super().unlink()
        self._bump_mip_plan_version()
        return res
