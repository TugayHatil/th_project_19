# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    # BRD §7.3 — inverse side of purchase.request.line.need_move_ids.
    # A raw material move linked here has already been transferred to a
    # purchase request and must not be requested again (BRD §7.2 dedup).
    purchase_need_request_line_ids = fields.Many2many(
        comodel_name="purchase.request.line",
        relation="purchase_request_line_need_move_rel",
        column1="move_id",
        column2="purchase_request_line_id",
        string="Satınalma Talebi Satırları",
        copy=False,
        readonly=True,
    )

    # fields that actually feed the plan — skipping the rest keeps the
    # version bump off the hot path of high-frequency move writes
    _PLAN_FIELDS = {
        "state", "product_id", "product_uom", "product_uom_qty",
        "location_id", "location_dest_id", "date", "date_deadline",
        "warehouse_id", "picking_id", "raw_material_production_id",
        "qty_picked", "picked", "sale_line_id",
    }

    # any move change can alter the material-need plan — bump the shared
    # plan version so cached plans rebuild on the next request
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return recs

    def write(self, vals):
        watch = {"date", "date_deadline"} & set(vals)
        old_dt = {}
        if watch:
            old_dt = {m.id: (m.date, m.date_deadline) for m in self}
        res = super().write(vals)
        if self._PLAN_FIELDS & set(vals):
            self.env["mrp.purchase.need"]._bump_plan_version()
        if old_dt:
            self._log_reschedules(old_dt)
        return res

    def _log_reschedules(self, old_dt):
        """Mint one history row per move whose planned date actually
        changed — the İstisna column's audit trail. Either date field
        counts: rescheduling a picking moves the move's date even when
        the customer deadline stays put."""
        now = fields.Datetime.now()
        vals_list = []
        for m in self:
            od, odd = old_dt[m.id]
            date_changed = m.date != od
            deadline_changed = m.date_deadline != odd
            if not (date_changed or deadline_changed):
                continue
            # show the field that actually moved — the deadline when
            # both shifted in one write
            new_planned = m.date_deadline if deadline_changed else m.date
            if not new_planned:
                continue
            # move dates are UTC datetimes — a 23:42 UTC write is the
            # next local day; the log must show the user's day
            planned = new_planned
            if isinstance(planned, datetime):
                planned = fields.Datetime.context_timestamp(
                    self, planned).date()
            vals_list.append({
                "key": "mv:%s" % m.id,
                "move_id": m.id,
                "doc_name": (
                    m.raw_material_production_id.name
                    or m.production_id.name
                    or m.picking_id.name or m.origin or ""),
                "user_id": self.env.uid,
                "change_date": now,
                "planned_date": planned,
                "company_id": m.company_id.id,
            })
        if vals_list:
            self.env["mip.reschedule.log"].sudo().create(vals_list)

    def unlink(self):
        res = super().unlink()
        self.env["mrp.purchase.need"]._bump_plan_version()
        return res


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # belt & suspenders: if a completion path ever bypasses
    # stock.move.write (low-level _write fast paths), the plan version
    # still bumps when a picking is validated
    def _action_done(self):
        res = super()._action_done()
        self.env["mrp.purchase.need"]._bump_plan_version()
        return res


class StockQuant(models.Model):
    _inherit = "stock.quant"

    _PLAN_FIELDS = {
        "quantity", "reserved_quantity", "location_id",
        "product_id", "product_uom_id",
    }

    # on-hand balances feed the plan walk directly — inventory
    # adjustments and quant reservations must refresh the cached plan
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env["mrp.purchase.need"]._bump_plan_version()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if self._PLAN_FIELDS & set(vals):
            self.env["mrp.purchase.need"]._bump_plan_version()
        return res
