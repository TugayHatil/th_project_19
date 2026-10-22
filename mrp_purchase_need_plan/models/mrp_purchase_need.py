# -*- coding: utf-8 -*-
from collections import defaultdict, deque
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
        groups = []
        for p in plan.values():
            payload = self._group_payload(p)
            # a fully covered product has nothing to plan; hide it unless
            # some need is already attached to a request (traceability)
            if payload["total_uncovered"] <= 0 \
                    and not payload["requested_count"]:
                continue
            groups.append(payload)
        groups.sort(key=lambda g: (g["earliest_start"], g["name"]))
        return {
            "groups": groups,
            "today": fields.Date.to_string(fields.Date.context_today(self)),
        }

    @api.model
    def get_need_lines(self, product_id, warehouse_id=False,
                       date_from=None, date_to=None):
        """Need detail rows for a single product group (BRD §3.2).

        The whole plan is computed even for a single product: virtual
        component rows exist only when the parent demand is part of the
        same computation."""
        product = self.env["product.product"].browse(int(product_id))
        plan = self._build_plan(
            warehouse_id, date_from, date_to, "", products=None)
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
                                line_keys=None, move_quantities=None,
                                warehouse_id=False,
                                date_from=None, date_to=None):
        """Merge uncovered needs of the selected need lines into purchase
        requests — one request per (company, warehouse) (BRD §7.1/§7.2).

        ``product_ids`` selects every uncovered need of those products;
        ``line_keys`` selects individual need rows (line-level picking —
        "mv:<id>" for real demands, "bom:…" for BoM-exploded ones);
        ``move_quantities`` additionally overrides the requested quantity
        of a selected row (planner-edited "Planla" input).

        Current stock and expected supply are re-evaluated right before
        creating the request (BRD §9 / Test 7). The advisory lock plus the
        already-requested check inside the same transaction prevents
        duplicate requests from concurrent runs (BRD §10 / Test 9).
        """
        if not product_ids and not move_ids and not line_keys \
                and not move_quantities:
            raise UserError(self.env._("En az bir ihtiyaç satırı seçin."))
        # serialize concurrent request creation for the whole screen
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext('mrp_purchase_need_plan'))")

        selected = None
        if move_ids:
            selected = {"mv:%s" % int(i) for i in move_ids}
        if line_keys:
            selected = (selected or set()) | {str(k) for k in line_keys}
        qty_map = {}
        if move_quantities:
            for k, v in move_quantities.items():
                # plain numbers are legacy move ids; need keys already
                # carry their "mv:"/"bom:" prefix
                sk = str(k)
                qty_map[sk if ":" in sk else "mv:%s" % sk] = float(v)
            for qty in qty_map.values():
                if qty <= 0:
                    raise UserError(self.env._(
                        "Talep miktarı sıfırdan büyük olmalıdır."))
            selected = (selected or set()) | set(qty_map)
        # the full plan is required: virtual component rows exist only
        # when the parent product's demand is part of the computation
        plan = self._build_plan(
            warehouse_id, date_from, date_to, "", products=None)
        product_filter = ({int(p) for p in product_ids}
                          if product_ids else None)

        # gather uncovered, not-yet-requested need lines per
        # (company, warehouse, product) — needs with incompatible
        # destinations must not merge into one request/line (BRD §8)
        grouped = defaultdict(lambda: defaultdict(dict))
        skipped = []
        for pid, data in plan.items():
            if product_filter is not None and pid not in product_filter:
                continue
            product = data["product"]
            if selected is not None and not any(
                    ln["key"] in selected for ln in data["lines"]):
                # none of this product's need rows was selected
                continue
            fresh = [
                ln for ln in data["lines"]
                if ln["requestable_qty"] > 0
                and ln.get("can_buy", True)
                and (selected is None or ln["key"] in selected)
            ]
            if not fresh:
                skipped.append(product.display_name)
                continue
            for ln in fresh:
                # planner-entered quantity overrides the remaining qty
                req_qty = qty_map.get(ln["key"], ln["requestable_qty"])
                key = (ln["company_id"], ln["warehouse_id"])
                entry = grouped[key][product.id]
                entry.setdefault("product", product)
                entry.setdefault("items", []).append((ln, req_qty))

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
                items = entry["items"]
                qty = sum(q for _ln, q in items)
                earliest = min(ln["need_date"] for ln, _q in items)
                move_ids = [ln["move_id"] for ln, _q in items
                            if ln["move_id"]]
                mip_ids = [ln["mip_id"] for ln, _q in items
                           if ln["mip_id"]]
                name = product.display_name
                line_cmds.append((0, 0, {
                    "product_id": product.id,
                    "name": name,
                    "product_qty": qty,
                    "product_uom_id": product.uom_id.id,
                    "date_required": earliest,
                    "estimated_cost": qty * product.standard_price,
                    "need_move_ids": [(6, 0, move_ids)],
                    "need_mip_ids": [(6, 0, mip_ids)],
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
                origins.update(
                    ln["source"] for ln, _q in entry["items"] if ln["source"])
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
        # durable MİP records are upserted on every plan build so each
        # need row gets a stable number without duplicating on refresh
        mip_by_move = self._ensure_mip_lines(need_moves)
        need_products = need_moves.product_id
        # BoM explosion graph: components of demanded manufactured
        # products become virtual needs, level by level (depth order so
        # every parent is processed before its components)
        bom_map, children, depth, comp_products = self._get_bom_graph(
            need_products)
        products = need_products | comp_products
        flow_moves = self._get_flow_moves(products, scope_ids)
        onhand = self._get_onhand(products, scope_ids)
        requested, req_docs, pend = self._get_requested_quantities(
            need_moves)
        lead_info = self._get_lead_info(products)
        route_sets = (self._get_buy_route_ids(), self._get_manu_route_ids())
        today = fields.Date.context_today(self)

        flow_by_product = defaultdict(lambda: self.env["stock.move"])
        for mv in flow_moves:
            flow_by_product[mv.product_id.id] |= mv
        need_by_product = defaultdict(lambda: self.env["stock.move"])
        for mv in need_moves:
            need_by_product[mv.product_id.id] |= mv

        plan = {}
        virtual_events = defaultdict(dict)  # pid -> {key: event dict}
        seen_keys = set()
        ordered = products.sorted(
            key=lambda p: depth.get(p.product_tmpl_id.id, 0))
        for product in ordered:
            ev_map = virtual_events.pop(product.id, {})
            seen_keys.update(ev_map)
            vevents = list(ev_map.values())
            vmips = self._ensure_virtual_mip(product, vevents)
            vreq, vdocs, vpend = self._get_virtual_requested(
                vevents, vmips)
            data = self._compute_product(
                product,
                need_by_product[product.id],
                flow_by_product[product.id],
                onhand.get(product.id, 0.0),
                scope_ids,
                requested,
                req_docs,
                pend,
                vevents,
                vmips,
                vreq,
                vdocs,
                vpend,
                mip_by_move,
                lead_info[product.id],
                today,
                route_sets,
            )
            self._sync_virtual_mips(vmips, data["lines"])
            if data["lines"]:
                plan[product.id] = data
                self._explode_bom(
                    product, data["lines"], bom_map, manu_route_ids=
                    route_sets[1], out=virtual_events)
        # virtual needs that vanished from the plan close their MİP
        # records — the history stays queryable (BRD §4.3)
        self._close_stale_virtual_mips(seen_keys, warehouse_id)
        return plan

    def _compute_product(self, product, need_moves, flow_moves, onhand,
                         scope_ids, requested, req_docs, pend, vevents,
                         vmips, vreq, vdocs, vpend, mip_by_move,
                         lead, today, route_sets):
        """Chronological stock walk for one product.

        Incoming and outgoing pending moves are applied in date order —
        receipts before issues on the same day. Each need line keeps the
        running balance right after its own consumption (the "forecast"
        column) and the incremental shortage it introduces (the
        "uncovered" quantity, BRD §6.2). ``vevents`` carries virtual
        (BoM-exploded) component demands — plain dicts keyed by their
        "bom:…" need key, treated exactly like outgoing demand rows.
        """
        need_set = set(need_moves.ids)

        def eid(mv):
            """Demand identity — move id for real needs, need key for
            virtual ones (mixed int/str keys never collide)."""
            return mv["key"] if isinstance(mv, dict) else mv.id
        need_keys = need_set | {ev["key"] for ev in vevents}
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
            # day-level chronology — the time-of-day must not decide
            # whether a receipt lands "late": a delivery due on the same
            # day as the need covers it
            mv_dt = self._need_dt(mv) if mv.id in need_set else mv.date
            events.append((self._local_date(
                mv_dt or fields.Datetime.now()), not src_in, mv, qty))
        for ev in vevents:
            events.append((ev["date"], False, ev, ev["qty"]))
        # receipts are applied before issues on the same date
        events.sort(key=lambda e: (e[0], 0 if e[1] else 1, str(eid(e[2]))))

        # route label, SAP BESKZ style: S = Satınal, Ü = Üret, S+Ü = both
        buy_ids, manu_ids = route_sets
        product_routes = set(product.route_ids.ids)
        parts = []
        if buy_ids & product_routes:
            parts.append("S")
        if manu_ids & product_routes:
            parts.append("Ü")
        route_abbr = "+".join(parts) or "-"

        balance = onhand
        deficit = 0.0
        detail = {}
        coverage_map = {}
        late_supplies = []  # incoming moves that land while short
        # FIFO pool of available supply — on-hand stock first, then every
        # incoming move in date order; needs consume it in chronology so
        # each line can report where its coverage came from
        pool = []
        if onhand > 0.0:
            pool.append({
                "kind": "stock",
                "kind_label": self.env._("Stok"),
                "name": self.env._("Mevcut stok"),
                "partner": "",
                "date": "",
                "order_id": False,
                "qty": onhand,
                "uom": product.uom_id.name,
            })
        for _date, incoming, mv, qty in events:
            prev_deficit = deficit
            balance = balance + qty if incoming else balance - qty
            deficit = max(0.0, -balance)
            if incoming:
                pool.append(self._supply_chunk(mv, qty))
                absorbed = prev_deficit - deficit
                if absorbed > 0.0:
                    late_supplies.append((mv, qty, absorbed))
            else:
                remaining_out = qty
                covers = []
                for chunk in pool:
                    if remaining_out <= 0.0:
                        break
                    take = min(chunk["qty"], remaining_out)
                    if take <= 0.0:
                        continue
                    chunk["qty"] -= take
                    remaining_out -= take
                    cover = dict(chunk)
                    cover["qty"] = take
                    covers.append(cover)
                if eid(mv) in need_keys:
                    # the part of the new shortage this need is
                    # responsible for
                    uncovered = min(qty, max(0.0, deficit - prev_deficit))
                    detail[eid(mv)] = {
                        "forecast": balance,
                        "uncovered": uncovered,
                    }
                    coverage_map[eid(mv)] = covers

        # Late supply that lands while a shortage exists could still serve
        # earlier uncovered needs if it were pulled forward. For open
        # purchase orders this yields a suggestion — purely informational:
        # until the planner actually reschedules the order, planning keeps
        # using its real delivery date and the need stays uncovered.
        ordered_needs = sorted(
            list(need_moves) + list(vevents),
            key=lambda e: (
                e["date"] if isinstance(e, dict)
                else self._local_date(self._need_dt(e)),
                str(eid(e))))

        def need_day(entry):
            return (entry["date"] if isinstance(entry, dict)
                    else self._local_date(self._need_dt(entry)))

        def req_of(entry):
            return (vreq.get(entry["key"], 0.0)
                    if isinstance(entry, dict)
                    else requested.get(entry.id, 0.0))
        suggest_map = defaultdict(float)
        suggestions = []
        for mv, qty, absorbed in late_supplies:
            supply_date = self._local_date(mv.date)
            remaining = absorbed
            covers = []
            for nmv in ordered_needs:
                if remaining <= 0.0:
                    break
                need_date = need_day(nmv)
                if need_date >= supply_date or eid(nmv) not in detail:
                    continue
                open_need = (
                    detail[eid(nmv)]["uncovered"]
                    - suggest_map[eid(nmv)]
                    - req_of(nmv))
                if open_need <= 0.0:
                    continue
                covered = min(open_need, remaining)
                suggest_map[eid(nmv)] += covered
                remaining -= covered
                covers.append((need_date, covered))
            po_line = mv.purchase_line_id
            order = po_line.order_id if po_line else self.env["purchase.order"]
            if order and order.state == "purchase" and covers:
                suggested = min(c[0] for c in covers)
                suggestions.append({
                    "kind": "pull",
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

        # Supply left in the pool after every need consumed its share is
        # no longer needed at all — a PO receipt standing there suggests
        # cancelling (nothing consumed) or reducing it (only part left).
        # A receipt that could still serve needs when pulled forward keeps
        # that suggestion exclusively — never both on the same order.
        pull_move_ids = {
            sug["move_id"] for sug in suggestions}
        for chunk in pool:
            if chunk["kind"] != "po" or chunk["qty"] <= 0.0 \
                    or chunk["move_id"] in pull_move_ids:
                continue
            suggestions.append({
                "kind": "cancel"
                    if chunk["qty"] >= chunk["orig_qty"] else "reduce",
                "move_id": chunk["move_id"],
                "order_id": chunk["order_id"],
                "order": chunk["name"],
                "partner": chunk["partner"],
                "order_qty": chunk["orig_qty"],
                "surplus_qty": chunk["qty"],
                "current_date": chunk["date"],
            })

        lines = []
        for mv in ordered_needs:
            if isinstance(mv, dict):
                # virtual (BoM-exploded) component need
                need_date = mv["date"]
                seller = product._select_seller(
                    quantity=mv["qty"], date=need_date,
                    uom_id=product.uom_id)
                delay = seller.delay if seller else 0
                approve_by = need_date - timedelta(days=delay)
                purchase_start = approve_by - timedelta(days=lead["proc"])
                info = detail.get(
                    mv["key"], {"forecast": balance, "uncovered": 0.0})
                req_qty = vreq.get(mv["key"], 0.0)
                requestable = max(0.0, info["uncovered"] - req_qty)
                mip = vmips.get(mv["key"], self.env["mip.need.line"])
                lines.append({
                    "key": mv["key"],
                    "move_id": False,
                    "virtual": True,
                    "mip_id": mip.id,
                    "mip_name": mip.name,
                    "company_id": mv["company_id"],
                    "warehouse_id": mv["warehouse_id"],
                    "need_date": fields.Date.to_string(need_date),
                    "location": mv["location"],
                    "route": route_abbr,
                    "source": " / ".join(sorted(mv["parents"]))
                        or self.env._("Üretim Planı"),
                    "source_type": "ÜP",
                    "onhand": onhand,
                    "forecast": info["forecast"],
                    "need_qty": mv["qty"],
                    "uncovered_qty": info["uncovered"],
                    "covered_qty": mv["qty"] - info["uncovered"],
                    "coverage": coverage_map.get(mv["key"], []),
                    "pending": vpend.get(mv["key"], []),
                    "pull_covered": suggest_map[mv["key"]],
                    "uom": product.uom_id.name,
                    "approve_by": fields.Date.to_string(approve_by),
                    "purchase_start": fields.Date.to_string(purchase_start),
                    "is_late": purchase_start < today,
                    "requested_qty": req_qty,
                    "requestable_qty": requestable,
                    "action": "",
                    "action_doc": "",
                    "already_requested":
                        req_qty > 0.0 and requestable <= 0.0,
                    "can_buy": bool(buy_ids & product_routes),
                    "missing_lead_config": lead["missing"],
                })
                continue
            qty = mv.product_uom._compute_quantity(
                self._move_open_qty(mv), product.uom_id, round=False)
            # MO components are needed when production is scheduled to
            # consume them (move.date); customer deliveries are needed by
            # the promised ship date (date_deadline, falling back to the
            # scheduled date)
            need_dt = self._need_dt(mv)
            if mv.raw_material_production_id:
                source = mv.raw_material_production_id.name
                source_type = "MO"
            else:
                source_type = "SO" if mv.location_dest_id.usage == "customer" else "-"
                if "sale_line_id" in mv._fields and mv.sale_line_id:
                    source = mv.sale_line_id.order_id.name
                else:
                    source = mv.origin or (
                        mv.picking_id.name if mv.picking_id else "")
            need_date = self._local_date(need_dt)
            seller = product._select_seller(
                quantity=qty, date=need_date, uom_id=product.uom_id)
            delay = seller.delay if seller else 0
            approve_by = need_date - timedelta(days=delay)
            purchase_start = approve_by - timedelta(days=lead["proc"])
            info = detail.get(mv.id, {"forecast": balance, "uncovered": 0.0})
            req_qty = requested.get(mv.id, 0.0)
            requestable = max(0.0, info["uncovered"] - req_qty)
            # informational exception flag: linked request/RFQ/PO is no
            # longer (fully) needed — nothing is cancelled automatically
            action, action_doc = "", ""
            if req_qty > 0.0 and info["uncovered"] <= 0.0:
                action = self.env._("İşlemi iptal et")
            elif req_qty > info["uncovered"]:
                action = self.env._("Miktarı azalt")
            elif suggest_map[mv.id] > 0.0:
                action = self.env._("İşlemi öne al")
            elif 0.0 < req_qty < info["uncovered"]:
                # part of the need already has a request; the remainder
                # can be added to it
                action = self.env._("Miktarı arttır")
            if action == self.env._("İşlemi öne al"):
                # a pull-forward always points at a confirmed PO
                action_doc = self.env._("Onaylı Sipariş")
            elif action:
                labels = sorted(req_docs.get(mv.id, ()), reverse=True)
                action_doc = " / ".join(dict.fromkeys(
                    label for _prio, label in labels))
            lines.append({
                "key": "mv:%s" % mv.id,
                "move_id": mv.id,
                "virtual": False,
                "mip_id": mip_by_move[mv.id].id,
                "mip_name": mip_by_move[mv.id].name,
                "company_id": mv.company_id.id,
                "warehouse_id": mv.warehouse_id.id,
                "need_date": fields.Date.to_string(need_date),
                "location": mv.location_id.display_name,
                "route": route_abbr,
                "source": source,
                "source_type": source_type,
                "onhand": onhand,
                "forecast": info["forecast"],
                "need_qty": qty,
                "uncovered_qty": info["uncovered"],
                "covered_qty": qty - info["uncovered"],
                "coverage": coverage_map.get(mv.id, []),
                "pending": pend.get(mv.id, []),
                "pull_covered": suggest_map[mv.id],
                "uom": product.uom_id.name,
                "approve_by": fields.Date.to_string(approve_by),
                "purchase_start": fields.Date.to_string(purchase_start),
                "is_late": purchase_start < today,
                "requested_qty": req_qty,
                "requestable_qty": requestable,
                "action": action,
                "action_doc": action_doc,
                "already_requested": req_qty > 0.0 and requestable <= 0.0,
                "can_buy": bool(buy_ids & product_routes),
                "missing_lead_config": lead["missing"],
            })
        return {
            "product": product,
            "moves": need_moves,
            "onhand": onhand,
            "end_balance": balance,
            "route": route_abbr,
            "lines": lines,
            "suggestions": suggestions,
        }

    def _group_payload(self, data):
        product = data["product"]
        lines = data["lines"]
        starts = [ln["purchase_start"] for ln in lines]
        locs = list(dict.fromkeys(ln["location"] for ln in lines))
        return {
            "product_id": product.id,
            "name": product.display_name,
            "code": product.default_code or "",
            "uom": product.uom_id.name,
            "onhand": data["onhand"],
            "end_forecast": data["end_balance"],
            "location": locs[0] if len(locs) == 1 else self.env._(
                "%s konum") % len(locs),
            "route": data["route"],
            "total_need": sum(ln["need_qty"] for ln in lines),
            "total_uncovered": sum(ln["uncovered_qty"] for ln in lines),
            "total_pending": sum(ln["requested_qty"] for ln in lines),
            "need_count": len(lines),
            "earliest_need": min(ln["need_date"] for ln in lines),
            "earliest_approve": min(ln["approve_by"] for ln in lines),
            "earliest_start": min(starts),
            "has_late": any(
                ln["is_late"] and ln["requestable_qty"] > 0
                for ln in lines),
            "missing_lead_config": any(ln["missing_lead_config"] for ln in lines),
            "requested_count": sum(
                1 for ln in lines if ln["requested_qty"] > 0),
            "suggestion_count": len(data.get("suggestions") or []),
        }

    # ------------------------------------------------------------------
    # data sources
    # ------------------------------------------------------------------

    @api.model
    def _local_date(self, dt):
        """User-timezone date of a datetime — plain Date.to_date would
        truncate the UTC value and show the previous day for
        local-midnight dates."""
        return fields.Datetime.context_timestamp(
            self, dt).date() if dt else None

    @api.model
    def _supply_chunk(self, move, qty):
        """One consumable supply unit for the FIFO coverage pool — a PO
        receipt, an MO output or any other expected receipt."""
        po_line = move.purchase_line_id
        kind, name, order_id, partner = "other", "", False, ""
        if po_line:
            order = po_line.order_id
            kind, order_id = "po", order.id
            name, partner = order.name, order.partner_id.display_name
        elif move.production_id:
            kind, name = "mo", move.production_id.name
        else:
            name = move.origin or (
                move.picking_id.name if move.picking_id
                else self.env._("Beklenen tedarik"))
        labels = {
            "po": self.env._("Satınalma Siparişi"),
            "mo": self.env._("Üretim Emri"),
            "stock": self.env._("Stok"),
            "other": self.env._("Tedarik"),
        }
        return {
            "kind": kind,
            "kind_label": labels[kind],
            "name": name,
            "partner": partner,
            "date": fields.Date.to_string(self._local_date(move.date)),
            "order_id": order_id,
            "move_id": move.id,
            "orig_qty": qty,
            "qty": qty,
            "uom": move.product_id.uom_id.name,
        }

    @api.model
    def _need_dt(self, move):
        """Planning date of a need move — components consume at the
        scheduled date, deliveries by the promised date (falls back to
        the scheduled date)."""
        if move.raw_material_production_id:
            return move.date
        return move.date_deadline or move.date

    @api.model
    def _ensure_mip_lines(self, need_moves):
        """Create/sync the persistent MİP record of every need move
        (BRD §4.1/§4.3). Returns {move_id: mip.need.line}.

        Records are keyed by move and the number is assigned once, so
        refreshes and re-computations never mint duplicates."""
        Mip = self.env["mip.need.line"].sudo()
        existing = Mip.search([("move_id", "in", need_moves.ids)])
        by_move = {rec.move_id.id: rec for rec in existing}
        missing = need_moves.filtered(lambda m: m.id not in by_move)
        if missing:
            created = Mip.create([{
                "key": "mv:%s" % mv.id,
                "move_id": mv.id,
                "product_id": mv.product_id.id,
                "company_id": mv.company_id.id,
                "warehouse_id": mv.warehouse_id.id,
                "location_id": mv.location_id.id,
                "need_date": self._local_date(self._need_dt(mv)),
                "source_type": "mo" if mv.raw_material_production_id
                    else "so" if mv.location_dest_id.usage == "customer"
                    else "other",
                "production_id": mv.raw_material_production_id.id or False,
                "uom_id": mv.product_id.uom_id.id,
                "initial_qty": mv.product_uom._compute_quantity(
                    mv.product_uom_qty, mv.product_id.uom_id, round=False),
            } for mv in missing])
            for rec in created:
                by_move[rec.move_id.id] = rec
        self.env["mip.need.line"].sudo().browse(
            [rec.id for rec in by_move.values()])._sync_from_moves()
        return by_move

    # ------------------------------------------------------------------
    # BoM explosion — virtual (planned) component needs
    # ------------------------------------------------------------------

    @api.model
    def _get_bom_graph(self, need_products):
        """BoM structure for demanded products.

        Returns (bom_map, children, depth, component_products):
          bom_map   {tmpl_id: mrp.bom} — normal/kit BoM per template
          depth     {tmpl_id: int}     — level in the explosion tree so
                                        parents are always processed
                                        before their components
          comp_ids  product.product set — every component variant found
                                        anywhere in the trees
        """
        Bom = self.env["mrp.bom"].sudo()
        manu_ids = self._get_manu_route_ids()
        bom_map, children, depth = {}, {}, {}
        comp_ids = set()
        need_tmpls = need_products.product_tmpl_id
        depth = {t: 0 for t in need_tmpls.ids}
        # only products that can actually be manufactured explode demand
        manu_products = need_products.filtered(
            lambda p: manu_ids & set(p.route_ids.ids))
        cur = set(manu_products.product_tmpl_id.ids)
        seen = set(need_tmpls.ids)
        guard = 0
        while cur and guard < 50:
            guard += 1
            boms = Bom.search([
                ("product_tmpl_id", "in", list(cur)),
                ("type", "in", ("normal", "phantom")),
            ])
            nxt = set()
            for bom in boms:
                t = bom.product_tmpl_id.id
                if t in bom_map:
                    continue
                bom_map[t] = bom
                for bl in bom.bom_line_ids:
                    comp = bl.product_id
                    if not comp:
                        continue
                    comp_ids.add(comp.id)
                    ct = comp.product_tmpl_id.id
                    children.setdefault(t, set()).add(ct)
                    if ct not in seen:
                        seen.add(ct)
                        nxt.add(ct)
            cur = nxt
        # BFS depth: a component is processed one level below the
        # deepest parent that produces it
        work = deque(need_tmpls.ids)
        while work:
            t = work.popleft()
            for ct in children.get(t, ()):
                if depth.get(ct, -1) <= depth[t]:
                    depth[ct] = depth[t] + 1
                    work.append(ct)
        comp_products = self.env["product.product"].browse(comp_ids)
        return bom_map, children, depth, comp_products

    @api.model
    def _explode_bom(self, product, lines, bom_map, manu_route_ids, out):
        """Turn the uncovered part of a manufactured product's needs
        into virtual component demands (dependent requirements).

        Only the shortage is exploded — quantities already covered by
        stock or incoming supply (including open MOs) produce no
        component need. The component is needed when production must
        start: need date minus the product's manufacturing lead time.
        """
        bom = bom_map.get(product.product_tmpl_id.id)
        if not bom or not (manu_route_ids & set(product.route_ids.ids)):
            return
        delay_days = product.produce_delay or 0
        for ln in lines:
            if ln["uncovered_qty"] <= 0.0:
                continue
            prod_date = fields.Date.to_date(
                ln["need_date"]) - timedelta(days=delay_days)
            for bl in bom.bom_line_ids:
                comp = bl.product_id
                if not comp:
                    continue
                qty = (ln["uncovered_qty"] * bl.product_qty
                       / (bom.product_qty or 1.0))
                if qty <= 0.0:
                    continue
                key = "bom:%s:%s:%s" % (
                    comp.id, ln["warehouse_id"] or 0,
                    fields.Date.to_string(prod_date))
                ev = out[comp.id].setdefault(key, {
                    "key": key,
                    "date": prod_date,
                    "qty": 0.0,
                    "parents": set(),
                    "company_id": ln["company_id"],
                    "warehouse_id": ln["warehouse_id"],
                    "location": ln["location"],
                })
                ev["qty"] += qty
                ev["parents"].add(product.display_name)

    @api.model
    def _ensure_virtual_mip(self, product, vevents):
        """Upsert MİP records for virtual need rows — {key: record}."""
        if not vevents:
            return {}
        Mip = self.env["mip.need.line"].sudo()
        keys = [ev["key"] for ev in vevents]
        by_key = {rec.key: rec for rec in Mip.search([("key", "in", keys)])}
        missing = [ev for ev in vevents if ev["key"] not in by_key]
        if missing:
            created = Mip.create([{
                "key": ev["key"],
                "product_id": product.id,
                "company_id": ev["company_id"],
                "warehouse_id": ev["warehouse_id"],
                "need_date": ev["date"],
                "source_type": "vp",
                "uom_id": product.uom_id.id,
                "initial_qty": ev["qty"],
            } for ev in missing])
            by_key.update({rec.key: rec for rec in created})
        return by_key

    @api.model
    def _sync_virtual_mips(self, vmips, lines):
        """Write the computed quantities/state onto virtual MİP records
        (they have no stock move to derive them from)."""
        for ln in lines:
            if not ln.get("virtual"):
                continue
            rec = vmips.get(ln["key"])
            if not rec:
                continue
            covered = ln["covered_qty"]
            if ln["uncovered_qty"] <= 0.0:
                state = "done"
            elif covered > 0.0:
                state = "partial"
            else:
                state = "open"
            doc_type, doc_no = rec._doc_summary()
            vals = {
                "need_date": fields.Date.to_date(ln["need_date"]),
                "current_qty": ln["need_qty"],
                "covered_qty": covered,
                "remaining_qty": ln["uncovered_qty"],
                "state": state,
                "doc_type": doc_type,
                "doc_no": doc_no,
            }
            diff = {
                k: v for k, v in vals.items()
                if rec._fields[k].type == "many2one" and rec[k].id != v
                or rec._fields[k].type != "many2one" and rec[k] != v}
            if diff:
                rec.write(diff)

    @api.model
    def _close_stale_virtual_mips(self, seen_keys, warehouse_id=False):
        """Virtual needs that disappeared from the current scope close
        their MİP record (cancelled) — history rows stay queryable."""
        domain = [
            ("key", "like", "bom:%"),
            ("state", "not in", ("done", "cancel")),
            ("company_id", "in", self.env.companies.ids),
        ]
        if warehouse_id:
            domain.append(("warehouse_id", "=", int(warehouse_id)))
        if seen_keys:
            domain.append(("key", "not in", list(seen_keys)))
        self.env["mip.need.line"].sudo().search(domain).write({
            "state": "cancel", "remaining_qty": 0.0})

    @api.model
    def _get_virtual_requested(self, vevents, vmips):
        """({key: requested qty}, {key: doc labels}, {key: pending docs})
        for virtual need keys linked through need_mip_ids."""
        if not vmips:
            return {}, {}, {}
        lines = self.env["purchase.request.line"].sudo().search([
            ("need_mip_ids", "in", [rec.id for rec in vmips.values()]),
            ("cancelled", "=", False),
            ("request_state", "in", list(ACTIVE_REQUEST_STATES)),
        ])
        demand = {ev["key"]: ev["qty"] for ev in vevents}
        mip_by_key = {rec.key: rec for rec in vmips.values()}
        alloc = defaultdict(float)
        docs = defaultdict(set)
        pend = defaultdict(list)
        for rl in lines:
            mips = [mip_by_key[k] for k in demand
                    if k in rl.need_mip_ids.mapped("key")]
            mips.sort(key=lambda m: (m.need_date or fields.Date.today(),
                                     m.id))
            labels = self._request_doc_labels(rl)
            for mip in mips:
                docs[mip.key] |= labels
            remaining = rl.product_uom_id._compute_quantity(
                rl.product_qty, rl.product_id.uom_id, round=False)
            takes = []
            last_key = None
            for mip in mips:
                if remaining <= 0.0:
                    break
                take = min(demand[mip.key], remaining)
                takes.append((mip, take))
                alloc[mip.key] += take
                remaining -= take
                last_key = mip.key
            if remaining > 0.0 and last_key is not None:
                alloc[last_key] += remaining
                mip, take = takes[-1]
                takes[-1] = (mip, take + remaining)
            req_label = self.env._("Onaysız Talep") \
                if rl.request_state in ("draft", "to_approve") \
                else self.env._("Onaylı Talep")
            for mip, take in takes:
                if take > 0.0:
                    pend[mip.key].append({
                        "type": req_label,
                        "doc": rl.request_id.name,
                        "model": "purchase.request",
                        "res_id": rl.request_id.id,
                        "qty": take,
                        "uom": mip.product_id.uom_id.name,
                        "date": fields.Date.to_string(rl.date_required)
                            if rl.date_required else "",
                    })
            for po_line in rl.purchase_lines:
                order = po_line.order_id
                if order.state not in ("draft", "sent"):
                    continue
                rem = po_line.product_uom_id._compute_quantity(
                    po_line.product_qty - po_line.qty_received,
                    po_line.product_id.uom_id, round=False)
                if rem <= 0.0:
                    continue
                po_label = self.env._("Onaysız Teklif")
                po_date = fields.Date.to_string(self._local_date(
                    po_line.date_planned or order.date_planned))
                left = rem
                last_mip = None
                for mip, take in takes:
                    if left <= 0.0:
                        break
                    share = min(take, left)
                    if share <= 0.0:
                        continue
                    pend[mip.key].append({
                        "type": po_label,
                        "doc": order.name,
                        "model": "purchase.order",
                        "res_id": order.id,
                        "qty": share,
                        "uom": mip.product_id.uom_id.name,
                        "date": po_date,
                    })
                    left -= share
                    last_mip = mip
                if left > 0.0 and last_mip is not None:
                    pend[last_mip.key][-1]["qty"] += left
        return dict(alloc), dict(docs), dict(pend)

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
        # this screen only plans purchasable goods: products must carry a
        # route containing a "buy" rule. Manufactured products with a BoM
        # are also pulled in — their own rows are not purchasable but
        # their uncovered demand explodes into component needs.
        buy_routes = self._get_buy_route_ids()
        manu_routes = self._get_manu_route_ids()
        domain = [
            ("state", "in", OPEN_STATES),
            ("product_uom_qty", ">", 0),
            # only inventory-tracked goods belong to material planning
            ("product_id.is_storable", "=", True),
            "|",
            ("product_id.route_ids", "in", list(buy_routes)),
            "&",
            ("product_id.route_ids", "in", list(manu_routes)),
            ("product_id.product_tmpl_id.bom_ids", "!=", False),
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
    def _get_requested_quantities(self, need_moves):
        """({move_id: requested qty}, {move_id: doc-type labels},
            {move_id: [pending doc entries]}).

        A merged request line is attributed to its need moves in
        need-date order — earliest needs are considered served first,
        matching the merge order — so a partially requested need line
        keeps its remaining quantity requestable (BRD §7.2). The second
        map describes the live purchasing document(s) behind each move —
        request or generated quotation/order — so the screen can flag
        documents that outlived their need. The third map lists those
        documents per move with the share attributed to the need, for
        the "Bekleyen" column detail dialog."""
        # sudo: dedup must work even for users who cannot read purchase
        # request lines directly (BRD §10)
        lines = self.env["purchase.request.line"].sudo().search([
            ("need_move_ids", "in", need_moves.ids),
            ("cancelled", "=", False),
            ("request_state", "in", list(ACTIVE_REQUEST_STATES)),
        ])
        need_by_id = {mv.id: mv for mv in need_moves}
        alloc = defaultdict(float)
        docs = defaultdict(set)
        pend = defaultdict(list)
        for rl in lines:
            moves = [need_by_id[i] for i in rl.need_move_ids.ids
                     if i in need_by_id]
            moves.sort(key=lambda m: (m.date or fields.Datetime.now(),
                                      m.id))
            labels = self._request_doc_labels(rl)
            for mv in moves:
                docs[mv.id] |= labels
            remaining = rl.product_uom_id._compute_quantity(
                rl.product_qty, rl.product_id.uom_id, round=False)
            takes = []
            last = None
            for mv in moves:
                if remaining <= 0.0:
                    break
                open_need = mv.product_uom._compute_quantity(
                    self._move_open_qty(mv), mv.product_id.uom_id,
                    round=False)
                take = min(open_need, remaining)
                takes.append((mv, take))
                alloc[mv.id] += take
                remaining -= take
                last = mv
            if remaining > 0.0 and last is not None:
                # planner asked for more than the raw need — attribute
                # the surplus to the latest need so sums stay truthful
                alloc[last.id] += remaining
                mv, take = takes[-1]
                takes[-1] = (mv, take + remaining)
            req_label = self.env._("Onaysız Talep") \
                if rl.request_state in ("draft", "to_approve") \
                else self.env._("Onaylı Talep")
            for mv, take in takes:
                if take > 0.0:
                    pend[mv.id].append({
                        "type": req_label,
                        "doc": rl.request_id.name,
                        "model": "purchase.request",
                        "res_id": rl.request_id.id,
                        "qty": take,
                        "uom": mv.product_id.uom_id.name,
                        "date": fields.Date.to_string(rl.date_required)
                            if rl.date_required else "",
                    })
            # downstream quotations raised from this request — confirmed
            # orders are already supply and show up under Karşılanan,
            # listing them here too would double-count
            for po_line in rl.purchase_lines:
                order = po_line.order_id
                if order.state not in ("draft", "sent"):
                    continue
                rem = po_line.product_uom_id._compute_quantity(
                    po_line.product_qty - po_line.qty_received,
                    po_line.product_id.uom_id, round=False)
                if rem <= 0.0:
                    continue
                po_label = self.env._("Onaysız Teklif")
                po_date = fields.Date.to_string(self._local_date(
                    po_line.date_planned or order.date_planned))
                left = rem
                last_mv = None
                for mv, take in takes:
                    if left <= 0.0:
                        break
                    share = min(take, left)
                    if share <= 0.0:
                        continue
                    pend[mv.id].append({
                        "type": po_label,
                        "doc": order.name,
                        "model": "purchase.order",
                        "res_id": order.id,
                        "qty": share,
                        "uom": mv.product_id.uom_id.name,
                        "date": po_date,
                    })
                    left -= share
                    last_mv = mv
                if left > 0.0 and last_mv is not None:
                    pend[last_mv.id][-1]["qty"] += left
        return dict(alloc), dict(docs), dict(pend)

    @api.model
    def _request_doc_labels(self, request_line):
        """{(priority, label)} describing which purchasing document a
        cancellation/reduce flag would point at — the generated PO/RFQ
        outranks the request itself."""
        labels = set()
        state = request_line.request_state
        if state in ("draft", "to_approve"):
            labels.add((1, self.env._("Onaysız Talep")))
        elif state in ("approved", "in_progress", "done"):
            labels.add((2, self.env._("Onaylı Talep")))
        for po_line in request_line.purchase_lines:
            order = po_line.order_id
            if order.state == "cancel" \
                    or po_line.product_qty <= po_line.qty_received:
                continue
            if order.state in ("draft", "sent"):
                labels.add((3, self.env._("Onaysız Teklif")))
            elif order.state == "purchase":
                labels.add((4, self.env._("Onaylı Sipariş")))
        return labels

    @api.model
    def _get_buy_route_ids(self):
        """Route ids that make a product purchasable ('buy' rule)."""
        routes = self.env["stock.route"].sudo().search(
            [("rule_ids.action", "=", "buy")])
        if not routes:
            routes = self.env.ref(
                "purchase_stock.route_warehouse0_buy",
                raise_if_not_found=False) or self.env["stock.route"]
        return set(routes.ids)

    @api.model
    def _get_manu_route_ids(self):
        """Route ids that make a product manufacturable."""
        routes = self.env["stock.route"].sudo().search(
            [("rule_ids.picking_type_id.code", "=", "mrp_operation")])
        if not routes:
            routes = self.env.ref(
                "mrp.route_warehouse0_manufacture",
                raise_if_not_found=False) or self.env["stock.route"]
        return set(routes.ids)

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
