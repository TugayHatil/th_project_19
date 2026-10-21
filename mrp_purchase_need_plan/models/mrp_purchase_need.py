# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

# Moves in these states are pending supply/demand, matching the set Odoo's
# own forecast uses (BRD §6.2).
OPEN_STATES = ("confirmed", "assigned", "partially_available")
# Request states that still reserve the need against a live request.
ACTIVE_REQUEST_STATES = ("draft", "to_approve", "approved", "in_progress", "done")


class MrpPurchaseNeed(models.AbstractModel):
    """Stateless service backing the Material Need Planning screen.

    No data is persisted here: needs, stock and forecasts are always read
    live from standard stock.move / stock.quant records (BRD §2, §9), and
    purchase requests are created through the standard purchase.request
    models (BRD §7).
    """

    _name = "mrp.purchase.need"
    _description = "Malzeme İhtiyaç ve Satınalma Planlama"

    # ------------------------------------------------------------------
    # public API used by the OWL screen
    # ------------------------------------------------------------------

    @api.model
    def get_filters(self):
        """Toolbar data: warehouses the user can see + PR create right."""
        warehouses = self.env["stock.warehouse"].search_read(
            [("company_id", "in", self.env.companies.ids)],
            ["name", "code"],
            order="name",
        )
        # creating requests stays governed by the standard purchase_request
        # ACLs (BRD §10); the screen only uses this to disable the button
        can_create = self.env["purchase.request"].has_access("create")
        return {
            "warehouses": [
                {"id": wh["id"], "name": wh["name"], "code": wh["code"]}
                for wh in warehouses
            ],
            "can_create_request": can_create,
            "today": fields.Date.to_string(fields.Date.context_today(self)),
        }

    @api.model
    def get_need_groups(self, warehouse_id=False, date_from=None,
                        date_to=None, query=""):
        """Product-grouped need summaries (BRD §3.1).

        Need lines are intentionally not serialized; they are fetched
        lazily per product via get_need_lines() when the user expands a
        group (BRD §9).
        """
        plan = self._build_plan(warehouse_id, date_from, date_to, query)
        groups = [self._group_payload(p) for p in plan.values()]
        groups.sort(key=lambda g: (g["earliest_start"], g["name"]))
        return {
            "groups": groups,
            "today": fields.Date.to_string(fields.Date.context_today(self)),
        }

    @api.model
    def get_need_lines(self, product_id, warehouse_id=False,
                       date_from=None, date_to=None):
        """Need detail rows for a single product group (BRD §3.2)."""
        product = self.env["product.product"].browse(int(product_id))
        plan = self._build_plan(
            warehouse_id, date_from, date_to, "", products=product)
        data = plan.get(product.id)
        if not data:
            return {"lines": [], "group": False, "suggestions": []}
        return {
            "lines": data["lines"],
            "group": self._group_payload(data),
            "suggestions": data["suggestions"],
        }

    @api.model
    def create_purchase_request(self, product_ids=None, move_ids=None,
                                warehouse_id=False,
                                date_from=None, date_to=None):
        """Merge uncovered needs of the selected need lines into purchase
        requests — one request per company (BRD §7.1/§7.2).

        ``product_ids`` selects every uncovered need of those products;
        ``move_ids`` selects individual need rows (line-level picking).

        Current stock and expected supply are re-evaluated right before
        creating the request (BRD §9 / Test 7). The advisory lock plus the
        already-requested check inside the same transaction prevents
        duplicate requests from concurrent runs (BRD §10 / Test 9).
        """
        if not product_ids and not move_ids:
            raise UserError(self.env._("En az bir ihtiyaç satırı seçin."))
        # serialize concurrent request creation for the whole screen
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext('mrp_purchase_need_plan'))")

        selected = None
        if move_ids:
            selected = {int(i) for i in move_ids}
        if product_ids:
            products = self.env["product.product"].browse(
                [int(p) for p in product_ids])
        else:
            products = self.env["stock.move"].browse(
                list(selected)).product_id
        plan = self._build_plan(
            warehouse_id, date_from, date_to, "", products=products)

        # gather uncovered, not-yet-requested need lines per
        # (company, warehouse, product) — needs with incompatible
        # destinations must not merge into one request/line (BRD §8)
        grouped = defaultdict(lambda: defaultdict(dict))
        skipped = []
        for product in products:
            data = plan.get(product.id)
            if not data:
                continue
            fresh = [
                ln for ln in data["lines"]
                if ln["uncovered_qty"] > 0 and not ln["already_requested"]
                and (selected is None or ln["move_id"] in selected)
            ]
            if selected is not None and not any(
                    ln["move_id"] in selected for ln in data["lines"]):
                # none of this product's need rows was selected
                continue
            if not fresh:
                skipped.append(product.display_name)
                continue
            for ln in fresh:
                key = (ln["company_id"], ln["warehouse_id"])
                entry = grouped[key][product.id]
                entry.setdefault("product", product)
                entry.setdefault("lines", []).append(ln)

        if not grouped:
            raise UserError(self.env._(
                "Seçilen ürünlerin tüm ihtiyaçları stok, beklenen tedarik "
                "veya mevcut bir satınalma talebi ile zaten karşılanıyor."
            ))

        Request = self.env["purchase.request"]
        created = []
        for (company_id, wh_id), product_map in grouped.items():
            line_cmds = []
            for entry in product_map.values():
                product = entry["product"]
                lines = entry["lines"]
                qty = sum(ln["uncovered_qty"] for ln in lines)
                earliest = min(ln["need_date"] for ln in lines)
                move_ids = [ln["move_id"] for ln in lines]
                name = product.display_name
                line_cmds.append((0, 0, {
                    "product_id": product.id,
                    "name": name,
                    "product_qty": qty,
                    "product_uom_id": product.uom_id.id,
                    "date_required": earliest,
                    "estimated_cost": qty * product.standard_price,
                    "need_move_ids": [(6, 0, move_ids)],
                }))
            if wh_id:
                picking_type = self.env["stock.warehouse"].browse(
                    wh_id).in_type_id
            else:
                picking_type = Request.with_context(
                    company_id=company_id)._default_picking_type()
            if not picking_type:
                raise UserError(self.env._(
                    "%s şirketi için mal kabul operasyon tipi bulunamadı.",
                    self.env["res.company"].browse(company_id).name,
                ))
            origins = set()
            for entry in product_map.values():
                origins.update(ln["source"] for ln in entry["lines"] if ln["source"])
            request = Request.create({
                "company_id": company_id,
                "picking_type_id": picking_type.id,
                "origin": ", ".join(sorted(origins))[:256],
                "description": self.env._(
                    "Malzeme İhtiyaç Planlama ekranından oluşturuldu."),
                "line_ids": line_cmds,
            })
            created.append({"id": request.id, "name": request.name})

        return {
            "requests": created,
            "skipped": skipped,
        }

    # ------------------------------------------------------------------
    # plan computation
    # ------------------------------------------------------------------

    @api.model
    def _build_plan(self, warehouse_id, date_from, date_to, query,
                    products=None):
        """Compute per-product need data.

        All heavy lifting is done with three batched reads — the need
        moves, every pending stock move for those products, and the quants
        — so the cost stays flat regardless of product count (BRD §9).

        Returns {product_id: {...}}; entry keys:
          product, onhand, moves (need moves), lines, total_need,
          total_uncovered, earliest_need, earliest_start, has_late,
          missing_lead_config, requested_count
        """
        scope_ids = set(self._get_scope_locations(warehouse_id).ids)
        need_moves = self._get_need_moves(
            scope_ids, date_from, date_to, query, products=products)
        if not need_moves:
            return {}
        products = need_moves.product_id
        flow_moves = self._get_flow_moves(products, scope_ids)
        onhand = self._get_onhand(products, scope_ids)
        requested = self._get_requested_move_ids(need_moves)
        lead_info = self._get_lead_info(products)
        today = fields.Date.context_today(self)

        flow_by_product = defaultdict(lambda: self.env["stock.move"])
        for mv in flow_moves:
            flow_by_product[mv.product_id.id] |= mv
        need_by_product = defaultdict(lambda: self.env["stock.move"])
        for mv in need_moves:
            need_by_product[mv.product_id.id] |= mv

        plan = {}
        for product in products:
            data = self._compute_product(
                product,
                need_by_product[product.id],
                flow_by_product[product.id],
                onhand.get(product.id, 0.0),
                scope_ids,
                requested,
                lead_info[product.id],
                today,
            )
            if data["lines"]:
                plan[product.id] = data
        return plan

    def _compute_product(self, product, need_moves, flow_moves, onhand,
                         scope_ids, requested, lead, today):
        """Chronological stock walk for one product.

        Incoming and outgoing pending moves are applied in date order —
        receipts before issues on the same day. Each need line keeps the
        running balance right after its own consumption (the "forecast"
        column) and the incremental shortage it introduces (the
        "uncovered" quantity, BRD §6.2).
        """
        events = []
        for mv in flow_moves:
            src_in = mv.location_id.id in scope_ids
            dst_in = mv.location_dest_id.id in scope_ids
            if src_in == dst_in:
                # either fully outside the scope or an internal transfer
                # inside it — neither changes the scoped balance
                continue
            qty = mv.product_uom._compute_quantity(
                self._move_open_qty(mv), product.uom_id, round=False)
            # receipts are applied before issues on the same date
            events.append((mv.date or fields.Datetime.now(), not src_in, mv, qty))
        events.sort(key=lambda e: (e[0], 0 if e[1] else 1, e[2].id))

        need_set = set(need_moves.ids)
        balance = onhand
        deficit = 0.0
        detail = {}
        late_supplies = []  # incoming moves that land while short
        for _date, incoming, mv, qty in events:
            prev_deficit = deficit
            balance = balance + qty if incoming else balance - qty
            deficit = max(0.0, -balance)
            if incoming:
                absorbed = prev_deficit - deficit
                if absorbed > 0.0:
                    late_supplies.append((mv, qty, absorbed))
            elif mv.id in need_set:
                # the part of the new shortage this need is responsible for
                uncovered = min(qty, max(0.0, deficit - prev_deficit))
                detail[mv.id] = {"forecast": balance, "uncovered": uncovered}

        # Late supply that lands while a shortage exists could still serve
        # earlier uncovered needs if it were pulled forward. For open
        # purchase orders this yields a suggestion — purely informational:
        # until the planner actually reschedules the order, planning keeps
        # using its real delivery date and the need stays uncovered.
        def _need_dt(mv):
            # components: scheduled consumption; deliveries: promised date
            if mv.raw_material_production_id:
                return mv.date
            return mv.date_deadline or mv.date

        ordered_needs = need_moves.sorted(key=lambda m: (_need_dt(m), m.id))
        suggest_map = defaultdict(float)
        suggestions = []
        for mv, qty, absorbed in late_supplies:
            supply_date = fields.Date.to_date(mv.date)
            remaining = absorbed
            covers = []
            for nmv in ordered_needs:
                if remaining <= 0.0:
                    break
                need_date = fields.Date.to_date(_need_dt(nmv))
                if (need_date >= supply_date or nmv.id in requested
                        or nmv.id not in detail):
                    continue
                open_need = (
                    detail[nmv.id]["uncovered"] - suggest_map[nmv.id])
                if open_need <= 0.0:
                    continue
                covered = min(open_need, remaining)
                suggest_map[nmv.id] += covered
                remaining -= covered
                covers.append((need_date, covered))
            po_line = mv.purchase_line_id
            order = po_line.order_id if po_line else self.env["purchase.order"]
            if order and order.state == "purchase" and covers:
                suggested = min(c[0] for c in covers)
                suggestions.append({
                    "move_id": mv.id,
                    "order_id": order.id,
                    "order": order.name,
                    "partner": order.partner_id.display_name,
                    "order_qty": qty,
                    "cover_qty": sum(c[1] for c in covers),
                    "current_date": fields.Date.to_string(supply_date),
                    "suggested_date": fields.Date.to_string(suggested),
                    "days": (supply_date - suggested).days,
                    "covers": [
                        {"need_date": fields.Date.to_string(d), "qty": q}
                        for d, q in sorted(covers)
                    ],
                })

        lines = []
        for mv in ordered_needs:
            qty = mv.product_uom._compute_quantity(
                self._move_open_qty(mv), product.uom_id, round=False)
            # MO components are needed when production is scheduled to
            # consume them (move.date); customer deliveries are needed by
            # the promised ship date (date_deadline, falling back to the
            # scheduled date)
            need_dt = _need_dt(mv)
            if mv.raw_material_production_id:
                source = mv.raw_material_production_id.name
            else:
                if "sale_line_id" in mv._fields and mv.sale_line_id:
                    source = mv.sale_line_id.order_id.name
                else:
                    source = mv.origin or (
                        mv.picking_id.name if mv.picking_id else "")
            need_date = fields.Date.to_date(need_dt)
            seller = product._select_seller(
                quantity=qty, date=need_date, uom_id=product.uom_id)
            delay = seller.delay if seller else 0
            approve_by = need_date - timedelta(days=delay)
            purchase_start = approve_by - timedelta(days=lead["proc"])
            info = detail.get(mv.id, {"forecast": balance, "uncovered": 0.0})
            lines.append({
                "move_id": mv.id,
                "company_id": mv.company_id.id,
                "warehouse_id": mv.warehouse_id.id,
                "need_date": fields.Date.to_string(need_date),
                "location": mv.location_id.display_name,
                "source": source,
                "onhand": onhand,
                "forecast": info["forecast"],
                "need_qty": qty,
                "uncovered_qty": info["uncovered"],
                "pull_covered": suggest_map[mv.id],
                "uom": product.uom_id.name,
                "approve_by": fields.Date.to_string(approve_by),
                "purchase_start": fields.Date.to_string(purchase_start),
                "is_late": purchase_start < today,
                "already_requested": mv.id in requested,
                "missing_lead_config": lead["missing"],
            })
        return {
            "product": product,
            "moves": need_moves,
            "onhand": onhand,
            "lines": lines,
            "suggestions": suggestions,
        }

    def _group_payload(self, data):
        product = data["product"]
        lines = data["lines"]
        starts = [ln["purchase_start"] for ln in lines]
        return {
            "product_id": product.id,
            "name": product.display_name,
            "code": product.default_code or "",
            "uom": product.uom_id.name,
            "onhand": data["onhand"],
            "total_need": sum(ln["need_qty"] for ln in lines),
            "total_uncovered": sum(ln["uncovered_qty"] for ln in lines),
            "need_count": len(lines),
            "earliest_need": min(ln["need_date"] for ln in lines),
            "earliest_start": min(starts),
            "has_late": any(
                ln["is_late"] and ln["uncovered_qty"] > 0
                and not ln["already_requested"] for ln in lines),
            "missing_lead_config": any(ln["missing_lead_config"] for ln in lines),
            "requested_count": sum(1 for ln in lines if ln["already_requested"]),
            "suggestion_count": len(data.get("suggestions") or []),
        }

    # ------------------------------------------------------------------
    # data sources
    # ------------------------------------------------------------------

    @api.model
    def _move_open_qty(self, move):
        """Remaining move demand in the move's UoM.

        Reserved-but-not-done lines keep the full demand (the stock has
        not left the building yet); already picked/done portions are
        subtracted so partially consumed component moves only report the
        still-needed remainder.
        """
        picked = sum(
            line.product_uom_id._compute_quantity(
                line.quantity, move.product_uom, round=False)
            for line in move.move_line_ids if line.picked
        )
        return move.product_uom_qty - picked


    @api.model
    def _get_scope_locations(self, warehouse_id):
        """Internal stock locations covered by the plan (BRD §6.1)."""
        Location = self.env["stock.location"]
        if warehouse_id:
            warehouse = self.env["stock.warehouse"].browse(int(warehouse_id))
            return Location.search([
                ("id", "child_of", warehouse.view_location_id.id),
                ("usage", "=", "internal"),
            ])
        return Location.search([
            ("usage", "=", "internal"),
            "|", ("company_id", "=", False),
            ("company_id", "in", self.env.companies.ids),
        ])

    @api.model
    def _get_need_moves(self, scope_ids, date_from, date_to, query,
                        products=None):
        """Open stock demands: manufacturing component moves and customer
        deliveries (BRD §1/§6.2)."""
        domain = [
            ("state", "in", OPEN_STATES),
            ("product_uom_qty", ">", 0),
            ("company_id", "in", self.env.companies.ids),
            ("location_id", "in", list(scope_ids)),
            "|",
            ("raw_material_production_id", "!=", False),
            ("location_dest_id.usage", "=", "customer"),
        ]
        if products:
            domain.append(("product_id", "in", products.ids))
        if date_from:
            domain.append(("date", ">=", f"{date_from} 00:00:00"))
        if date_to:
            domain.append(("date", "<=", f"{date_to} 23:59:59"))
        if query:
            domain += ["|", ("product_id.name", "ilike", query),
                       ("product_id.default_code", "ilike", query)]
        return self.env["stock.move"].search(domain)

    @api.model
    def _get_flow_moves(self, products, scope_ids):
        """Every pending move touching the scope for the given products —
        incoming receipts, open POs, MO outputs and all outgoing demands
        (BRD §6.2). One query for the whole product set."""
        return self.env["stock.move"].search([
            ("product_id", "in", products.ids),
            ("state", "in", OPEN_STATES),
            ("company_id", "in", self.env.companies.ids),
            "|", ("location_id", "in", list(scope_ids)),
            ("location_dest_id", "in", list(scope_ids)),
        ])

    @api.model
    def _get_onhand(self, products, scope_ids):
        """On-hand quantity per product inside the scope (BRD §6.1).

        Deliberately the physical on-hand figure (stock.quant.quantity);
        expected supply and demand are applied on top as forecast events,
        so reserved units are never double-counted.
        """
        result = {}
        for product, qty in self.env["stock.quant"]._read_group(
            [("product_id", "in", products.ids),
             ("location_id", "in", list(scope_ids))],
            ["product_id"],
            ["quantity:sum"],
        ):
            result[product.id] = qty
        return result

    @api.model
    def _get_requested_move_ids(self, need_moves):
        """Need moves already attached to a live purchase request line —
        the dedup guard of BRD §7.2."""
        # sudo: dedup must work even for users who cannot read purchase
        # request lines directly (BRD §10)
        lines = self.env["purchase.request.line"].sudo().search([
            ("need_move_ids", "in", need_moves.ids),
            ("cancelled", "=", False),
            ("request_state", "in", list(ACTIVE_REQUEST_STATES)),
        ])
        return set(lines.need_move_ids.ids)

    @api.model
    def _get_lead_info(self, products):
        """Purchase-process days per product (BRD §4.3).

        Product card wins; otherwise the global default. When neither is
        configured the product is flagged so the screen can warn instead
        of silently planning with zero days (BRD §4.3).
        """
        Param = self.env["ir.config_parameter"].sudo()
        raw = Param.get_param("mrp_purchase_need_plan.default_process_days")
        default_set = raw not in (None, "")
        default_days = int(raw) if default_set else 0
        info = {}
        for product in products:
            proc = product.x_purchase_process_days
            if proc:
                info[product.id] = {"proc": proc, "missing": False}
            elif default_set:
                info[product.id] = {"proc": default_days, "missing": False}
            else:
                info[product.id] = {"proc": 0, "missing": True}
        return info
