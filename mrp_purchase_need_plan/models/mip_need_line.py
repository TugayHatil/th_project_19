# -*- coding: utf-8 -*-
from odoo import api, fields, models

# live request states whose documents still count as related supply docs
_ACTIVE_REQUEST_STATES = ("draft", "to_approve", "approved", "in_progress", "done")


class MipNeedLine(models.Model):
    """Persistent tracking record for a single material need line.

    Planning rows are computed live from volatile ``stock.move`` demand;
    this model gives every need row a durable MİP number so fulfilled or
    cancelled needs stay queryable after leaving the active screen
    (BRD §4.1/§4.3). One record per need move, number never reused.
    """

    _name = "mip.need.line"
    _description = "MİP İhtiyaç Kaydı"
    _inherit = ["mail.thread"]
    _order = "id desc"
    _check_company_auto = True

    _sql_constraints = [(
        "key_uniq",
        "unique(key)",
        "Her ihtiyaç anahtarı için yalnızca bir MİP kaydı oluşturulabilir.",
    ), (
        "name_uniq",
        "unique(name)",
        "MİP numaraları benzersiz olmalıdır.",
    )]

    name = fields.Char(
        "MİP No", readonly=True, copy=False, index=True,
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "mip.need.line"))
    # stable identity of the need — "mv:<move id>" for real stock demands,
    # "bom:<product id>:<date>" for BoM-exploded (planned) component needs
    key = fields.Char("İhtiyaç Anahtarı", readonly=True, required=True,
                      index=True)
    move_id = fields.Many2one(
        "stock.move", string="İhtiyaç Hareketi", ondelete="set null",
        readonly=True, index=True)
    product_id = fields.Many2one(
        "product.product", readonly=True, index=True)
    product_code = fields.Char(related="product_id.default_code", store=True)
    company_id = fields.Many2one("res.company", readonly=True, index=True)
    warehouse_id = fields.Many2one(
        "stock.warehouse", readonly=True, index=True)
    location_id = fields.Many2one("stock.location", string="Konum",
                                  readonly=True)
    source_type = fields.Selection([
        ("mo", "MO"),
        ("so", "SO"),
        ("vp", "ÜP"),
        ("other", "-"),
    ], string="Tür", readonly=True)
    production_id = fields.Many2one("mrp.production", string="Üretim Emri",
                                    readonly=True)
    need_date = fields.Date("İhtiyaç Tarihi", readonly=True, index=True)
    initial_qty = fields.Float("İlk İhtiyaç Miktarı", readonly=True)
    current_qty = fields.Float("Güncel İhtiyaç Miktarı", readonly=True)
    covered_qty = fields.Float("Karşılanan Miktar", readonly=True,
                               tracking=True)
    remaining_qty = fields.Float("Kalan Miktar", readonly=True)
    uom_id = fields.Many2one("uom.uom", string="Birim", readonly=True)
    state = fields.Selection([
        ("open", "Açık"),
        ("partial", "Kısmen Karşılandı"),
        ("done", "Karşılandı"),
        ("cancel", "İptal Edildi"),
    ], string="Durum", default="open", readonly=True, index=True,
        tracking=True)
    # summary columns for the tracking list; refreshed on every sync so
    # they stay searchable (BRD §4.2)
    doc_type = fields.Char("Belge Türü", readonly=True)
    doc_no = fields.Char("Belge No", readonly=True)
    # clickable relations for the detail form (computed on read)
    request_ids = fields.Many2many(
        "purchase.request", string="Satınalma Talepleri",
        compute="_compute_doc_links")
    purchase_order_ids = fields.Many2many(
        "purchase.order", string="Satınalma Belgeleri",
        compute="_compute_doc_links")
    sale_order_id = fields.Many2one(
        "sale.order", string="Satış Siparişi", compute="_compute_doc_links")

    # ------------------------------------------------------------------
    # related documents
    # ------------------------------------------------------------------

    def _linked_request_lines(self):
        """Open purchase.request lines serving this need — linked via the
        raw need move or directly via this MİP record (virtual needs)."""
        domain = [("cancelled", "=", False),
                  ("request_state", "in", list(_ACTIVE_REQUEST_STATES))]
        if self.move_id:
            domain = ["&"] + domain + [
                "|",
                ("need_move_ids", "in", self.move_id.ids),
                ("need_mip_ids", "in", self.ids)]
        else:
            domain.append(("need_mip_ids", "in", self.ids))
        return self.env["purchase.request.line"].sudo().search(domain)

    @api.depends("move_id")
    def _compute_doc_links(self):
        for rec in self:
            req_lines = rec._linked_request_lines()
            po_lines = req_lines.purchase_lines
            rec.request_ids = req_lines.request_id
            rec.purchase_order_ids = po_lines.order_id
            rec.sale_order_id = (
                rec.move_id.sale_line_id.order_id
                if rec.move_id and "sale_line_id" in rec.move_id._fields
                else self.env["sale.order"])

    def _doc_summary(self):
        """(doc_type, doc_no) text pair for the list/search columns."""
        types, nos = [], []
        if self.production_id:
            types.append(self.env._("Üretim Emri"))
            nos.append(self.production_id.name)
        if self.sale_order_id:
            types.append(self.env._("Satış Siparişi"))
            nos.append(self.sale_order_id.name)
        if self.request_ids:
            types.append(self.env._("Satınalma Talebi"))
            nos += self.request_ids.mapped("name")
        for order in self.purchase_order_ids:
            label = (self.env._("Satınalma Siparişi")
                     if order.state == "purchase"
                     else self.env._("Teklif"))
            if label not in types:
                types.append(label)
            nos.append(order.name)
        return " / ".join(types), ", ".join(nos)

    # ------------------------------------------------------------------
    # synchronization
    # ------------------------------------------------------------------

    def _sync_from_moves(self):
        """Refresh quantities, dates, docs and state from the source move.

        Only realized quantities count as covered: an issued but
        unfinished purchase order does not fulfil the need (BRD §4.5).
        Unchanged records are not written so write_date and the chatter
        history stay meaningful.
        """
        Need = self.env["mrp.purchase.need"]
        for rec in self:
            mv = rec.move_id
            if not mv and rec.key.startswith("bom:"):
                # virtual (BoM-exploded) needs are synced by the plan
                # build itself, not by move states — skip them here
                continue
            if not mv or mv.state == "cancel":
                vals = {"state": "cancel", "remaining_qty": 0.0}
            else:
                cur = mv.product_uom._compute_quantity(
                    mv.product_uom_qty, rec.product_id.uom_id, round=False)
                open_qty = mv.product_uom._compute_quantity(
                    Need._move_open_qty(mv), rec.product_id.uom_id,
                    round=False)
                covered = max(0.0, cur - open_qty)
                if covered <= 0.0:
                    state = "open"
                elif covered >= cur:
                    state = "done"
                else:
                    state = "partial"
                vals = {
                    "need_date": Need._local_date(Need._need_dt(mv)),
                    "production_id": mv.raw_material_production_id.id or False,
                    "current_qty": cur,
                    "covered_qty": covered,
                    "remaining_qty": open_qty,
                    "state": state,
                }
            diff = {}
            for k, v in vals.items():
                if self._fields[k].type == "many2one":
                    if rec[k].id != v:
                        diff[k] = v
                elif rec[k] != v:
                    diff[k] = v
            if diff or not rec.doc_no:
                # linked-document search is the expensive part of this
                # sync — run it only for records that actually changed
                doc_type, doc_no = rec._doc_summary()
                if rec.doc_type != doc_type:
                    diff["doc_type"] = doc_type
                if rec.doc_no != doc_no:
                    diff["doc_no"] = doc_no
            if diff:
                # bulk bookkeeping writes skip chatter tracking — one
                # message per record would flood both mail and memory
                rec.with_context(tracking_disable=True).write(diff)

    @api.model
    def _cron_sync(self):
        """Nightly sweep: register new needs and refresh open records.

        Needs that left the active screen (done/cancelled moves) flip to
        their terminal state here even when nobody opens the planner.
        """
        Need = self.env["mrp.purchase.need"]
        scope_ids = set(Need._get_scope_locations(False).ids)
        moves = Need._get_need_moves(scope_ids, None, None, "")
        Need._ensure_mip_lines(moves)
        self.search([
            ("state", "not in", ("done", "cancel")),
            ("move_id", "!=", False),
        ])._sync_from_moves()
