# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProjectMaterialPlan(models.Model):
    """Line-level availability/delay read (BRD §6.2/§6.3).

    All quantities come from the linked ``stock.move`` records created by
    ``project_resource_planning`` — no parallel availability engine:

    * delivered moves contribute their real ``quantity``;
    * open moves contribute ``forecast_availability`` (what Odoo expects
      in stock by the move's date) and the worst
      ``forecast_expected_date`` across them.

    ``material_state`` vocabulary: ``ready`` / ``partial`` / ``delayed`` /
    ``unknown``. Unknown means Odoo has no data to prove availability —
    it must never read as "ready" (BRD §28).
    """

    _inherit = "project.material.plan"

    available_quantity = fields.Float(
        string="Available Quantity", compute="_compute_material_availability",
        digits="Product Unit of Measure", store=True,
    )
    shortage_quantity = fields.Float(
        string="Shortage Quantity", compute="_compute_material_availability",
        digits="Product Unit of Measure", store=True,
    )
    expected_availability_date = fields.Datetime(
        string="Expected Availability",
        compute="_compute_material_availability", store=True,
    )
    material_delay_days = fields.Float(
        string="Material Delay (Days)", compute="_compute_material_availability",
        digits=(16, 1), store=True,
    )
    material_state = fields.Selection(
        [
            ("ready", "Ready"),
            ("partial", "Partial Availability"),
            ("delayed", "Delayed"),
            ("unknown", "Unknown"),
        ],
        string="Material State", compute="_compute_material_availability",
        store=True,
    )

    @api.depends(
        "planned_quantity", "required_date",
        "move_ids", "move_ids.product_uom_qty",
        "move_ids.state", "move_ids.quantity", "move_ids.date",
        "move_ids.forecast_availability", "move_ids.forecast_expected_date",
    )
    def _compute_material_availability(self):
        for line in self:
            moves = line.move_ids
            done = moves.filtered(lambda m: m.state == "done")
            open_moves = moves - done - moves.filtered(
                lambda m: m.state == "cancel")
            done_qty = sum(done.mapped("quantity"))
            if not moves:
                # Draft line — nothing ordered yet, nothing provable.
                line.available_quantity = 0.0
                line.shortage_quantity = line.planned_quantity
                line.expected_availability_date = False
                line.material_delay_days = 0.0
                line.material_state = "unknown"
                continue
            # Odoo reports reserved quantity and forecast availability as
            # two regimes: an assigned move's forecast already contains
            # its reservation (10/10), while a partially assigned move
            # reports only what is still expected (0 beyond the reserved
            # 4). Taking the per-move maximum covers both without ever
            # double-counting physical stock.
            expected_qty = done_qty + sum(
                max(mv.quantity or 0.0, mv.forecast_availability or 0.0)
                for mv in open_moves
            )
            # Expected full-availability date = the worst open move's
            # forecast date (its scheduled date when no forecast exists).
            expected_dates = [
                mv.forecast_expected_date or mv.date
                for mv in open_moves if mv.forecast_expected_date or mv.date
            ]
            expected = max(expected_dates) if expected_dates else False
            required_dt = (
                fields.Datetime.to_datetime(line.required_date)
                if line.required_date else False
            )
            delay_days = 0.0
            if expected and required_dt and expected > required_dt:
                delay_days = (expected - required_dt).total_seconds() / 86400.0
            if not open_moves and not done:
                state = "unknown"
            elif delay_days > 0:
                state = "delayed"
            elif expected_qty < line.planned_quantity - 0.000001:
                # Confirmed zero availability is a delay, not "no data":
                # the requirement provably cannot be met in time.
                state = "partial" if expected_qty > 0.000001 else "delayed"
            elif open_moves and not expected:
                # Stock is open but Odoo has no date it can promise —
                # never read as available (BRD §28).
                state = "unknown"
            else:
                state = "ready"
            line.available_quantity = expected_qty
            line.shortage_quantity = max(
                0.0, line.planned_quantity - expected_qty)
            line.expected_availability_date = expected
            line.material_delay_days = delay_days
            line.material_state = state
