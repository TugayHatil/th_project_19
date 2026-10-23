# -*- coding: utf-8 -*-
import base64
import hashlib
import json
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from pytz import timezone, utc

# Moves in these states are pending supply/demand, matching the set Odoo's
# own forecast uses (BRD §6.2).
OPEN_STATES = ("confirmed", "assigned", "partially_available")
# Request states that still reserve the need against a live request.
ACTIVE_REQUEST_STATES = ("draft", "to_approve", "approved", "in_progress", "done")

# ------------------------------------------------------------------
# plan result cache — the whole computation is pure data (no recordsets)
# so a computed plan can safely outlive its request for a short TTL.
# Per-process LRU: each worker keeps at most _PLAN_CACHE_MAX entries.
# ------------------------------------------------------------------
_PLAN_CACHE = {}
_PLAN_CACHE_LOCK = threading.Lock()
# TTL is only a memory/backstop bound — correctness comes from the
# shared plan version bumped by stock.move / quant / request / BoM /
# product write hooks, so a quiet system serves the cache for a long
# time and any data change rebuilds on the next request.
_PLAN_CACHE_TTL = 3600.0  # seconds
_PLAN_CACHE_MAX = 8

# stock.move fields read once per build — plain dicts from here on, the
# per-record ORM attribute access is what used to make large plans crawl
_MOVE_FIELDS = [
    "id", "product_id", "state", "date", "date_deadline",
    "product_uom", "product_uom_qty", "location_id", "location_dest_id",
    "company_id", "warehouse_id", "origin", "picking_id",
    "purchase_line_id", "production_id", "raw_material_production_id",
]

_MIP_CHUNK = 1000

# MİP record creation is bounded per build so a bulk-loaded dataset can
# never blow the request-time limit on its first refresh: the backlog
# drains in the background via the warm-up cron (flag below tells the
# cron to keep rebuilding until every need row owns a record)
_MIP_ENSURE_INLINE = 1500   # request-path builds
_MIP_ENSURE_CRON = 4000     # warm-up cron builds
_MIP_BACKLOG_PARAM = "mrp_purchase_need_plan.mip_backlog"


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
                        date_to=None, query="", limit=None, offset=0,
                        uncovered_only=False, late_only=False,
                        sort_by="purchase_start", force=False):
        """Product-grouped need summaries (BRD §3.1), server-paged.

        Need lines are intentionally not serialized; they are fetched
        lazily per product via get_need_lines() when the user expands a
        group (BRD §9). Pagination, the uncovered/late filters and the
        sort all happen on the already-computed plan so the payload stays
        small regardless of how many products exist (BRD §9)."""
        plan = self._get_plan(
            warehouse_id, date_from, date_to, query, force=force)
        groups = []
        for p in plan.values():
            payload = self._group_payload(p)
            # a fully covered product has nothing to plan; hide it unless
            # some need is already attached to a request (traceability)
            if payload["total_uncovered"] <= 0 \
                    and not payload["requested_count"]:
                continue
            if uncovered_only and payload["total_uncovered"] <= 0:
                continue
            if late_only and not payload["has_late"]:
                continue
            groups.append(payload)
        key = "earliest_need" if sort_by == "need_date" else "earliest_start"
        groups.sort(key=lambda g: (g[key], g["name"]))
        total = len(groups)
        if limit:
            groups = groups[int(offset or 0):int(offset or 0) + int(limit)]
        return {
            "groups": groups,
            "total": total,
            "today": fields.Date.to_string(fields.Date.context_today(self)),
        }

    @api.model
    def get_need_lines(self, product_id, warehouse_id=False,
                       date_from=None, date_to=None):
        """Need detail rows for a single product group (BRD §3.2).

        The whole plan is computed even for a single product: virtual
        component rows exist only when the parent demand is part of the
        same computation. Served from the shared plan cache, so expanding
        a group right after load does not recompute anything."""
        plan = self._get_plan(warehouse_id, date_from, date_to, "")
        data = plan.get(int(product_id))
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
        # when the parent product's demand is part of the computation —
        # and it must be fresh right before creating documents (BRD §9)
        plan = self._get_plan(
            warehouse_id, date_from, date_to, "", force=True)
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
                skipped.append(product["display_name"])
                continue
            for ln in fresh:
                # planner-entered quantity overrides the remaining qty
                req_qty = qty_map.get(ln["key"], ln["requestable_qty"])
                key = (ln["company_id"], ln["warehouse_id"])
                entry = grouped[key][pid]
                entry.setdefault("product", product)
                entry.setdefault("items", []).append((ln, req_qty))

        if not grouped:
            raise UserError(self.env._(
                "Seçilen ürünlerin tüm ihtiyaçları stok, beklenen tedarik "
                "veya mevcut bir satınalma talebi ile zaten karşılanıyor."
            ))

        # selected rows must own their durable MİP record before the
        # request links to it (need_mip_ids traceability) — when the
        # background backlog has not minted them yet, mint just this
        # selection now
        missing_moves = {ln["move_id"] for pm in grouped.values()
                         for e in pm.values() for ln, _q in e["items"]
                         if ln["move_id"] and not ln["mip_id"]}
        mip_map = {}
        if missing_moves:
            mip_map = {mid: i["id"] for mid, i in self._ensure_mip_lines(
                self.env["stock.move"].browse(
                    sorted(missing_moves)))[0].items()}
        missing_vevs = [
            {"key": ln["key"], "date": ln["need_date"],
             "qty": ln["need_qty"], "company_id": ln["company_id"],
             "warehouse_id": ln["warehouse_id"]}
            for pm in grouped.values() for e in pm.values()
            for ln, _q in e["items"]
            if ln["virtual"] and not ln["mip_id"]]
        vmip_map = {}
        if missing_vevs:
            vmip_map = {k: i["id"] for k, i in
                        self._ensure_virtual_mips(missing_vevs)[0].items()}
        if mip_map or vmip_map:
            for pm in grouped.values():
                for e in pm.values():
                    for ln, _q in e["items"]:
                        if not ln["mip_id"]:
                            ln["mip_id"] = (
                                vmip_map.get(ln["key"]) if ln["virtual"]
                                else mip_map.get(ln["move_id"]))

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
                line_cmds.append((0, 0, {
                    "product_id": product["id"],
                    "name": product["display_name"],
                    "product_qty": qty,
                    "product_uom_id": product["uom_id"],
                    "date_required": earliest,
                    "estimated_cost": qty * product["standard_price"],
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

        # the plan cache now describes the pre-request world — drop it so
        # the next screen load re-reads stock and live request links
        self._invalidate_plan_cache()
        return {
            "requests": created,
            "skipped": skipped,
        }

    # ------------------------------------------------------------------
    # plan cache
    # ------------------------------------------------------------------

    @api.model
    def _plan_cache_key(self, warehouse_id, date_from, date_to, query):
        return (
            self.env.cr.dbname,
            self.env.uid,
            tuple(sorted(self.env.companies.ids)),
            self._plan_version(),
            int(warehouse_id) if warehouse_id else 0,
            str(date_from or ""), str(date_to or ""), str(query or ""),
        )

    @api.model
    def _plan_version(self):
        """Shared plan revision — bumped by write hooks on every model
        the plan depends on (moves, quants, request lines, BoMs, product
        lead data). Stored in ir.config_parameter so every worker sees
        the same version."""
        return self.env["ir.config_parameter"].sudo().get_param(
            "mrp_purchase_need_plan.plan_version", "0")

    @api.model
    def _bump_plan_version(self):
        P = self.env["ir.config_parameter"].sudo()
        P.set_param(
            "mrp_purchase_need_plan.plan_version",
            str(int(P.get_param(
                "mrp_purchase_need_plan.plan_version", "0") or "0") + 1))

    @api.model
    def _get_plan(self, warehouse_id, date_from, date_to, query,
                  force=False, allow_stale=True):
        """Shared plan accessor — a computed plan is pure data, so it can
        be reused by detail calls and repeated loads.

        Two cache tiers: the per-process LRU and a persisted JSON
        snapshot (ir.attachment) so cold workers and restarts stay fast.
        A snapshot whose stored version differs from the current plan
        version is served only while it is young — that grace window
        lets the warm-up cron rebuild after writes instead of making a
        user request pay the full recompute."""
        key = self._plan_cache_key(warehouse_id, date_from, date_to, query)
        now = fields.Datetime.now().timestamp()
        name = self._snapshot_name(warehouse_id, date_from, date_to, query)
        if not force:
            with _PLAN_CACHE_LOCK:
                entry = _PLAN_CACHE.get(key)
                if entry and now - entry[0] < _PLAN_CACHE_TTL:
                    return entry[1]
            snap = self._load_snapshot(name, allow_stale=allow_stale)
            if snap is not None:
                with _PLAN_CACHE_LOCK:
                    while len(_PLAN_CACHE) >= _PLAN_CACHE_MAX:
                        _PLAN_CACHE.pop(next(iter(_PLAN_CACHE)))
                    _PLAN_CACHE[key] = (now, snap)
                return snap
        # MİP record sync is bookkeeping for the MİP list, not part of
        # the plan payload — it stays off the request path (the warm-up
        # cron runs it) so a forced refresh only pays the compute
        plan = self._build_plan(
            warehouse_id, date_from, date_to, query, run_sync=False)
        self._store_snapshot(name, plan)
        with _PLAN_CACHE_LOCK:
            while len(_PLAN_CACHE) >= _PLAN_CACHE_MAX:
                _PLAN_CACHE.pop(next(iter(_PLAN_CACHE)))
            _PLAN_CACHE[key] = (now, plan)
        return plan

    # ---- persisted plan snapshots ------------------------------------

    _PLAN_SNAPSHOT_MAX_AGE = 300.0  # staleness grace after a write
    # payload schema — bump whenever the serialized plan shape changes;
    # a snapshot written by older code is rejected outright since its
    # missing keys would silently break new frontend features
    _PLAN_SCHEMA = 4

    def _snapshot_name(self, warehouse_id, date_from, date_to, query):
        """Stable attachment name per filter scope — version is carried
        inside the payload so a rebuild overwrites the same snapshot."""
        raw = repr((
            self.env.cr.dbname,
            tuple(sorted(self.env.companies.ids)),
            self.env.user.tz or "UTC",
            int(warehouse_id) if warehouse_id else 0,
            str(date_from or ""), str(date_to or ""), str(query or ""),
        ))
        return "mnp.plan." + hashlib.sha1(raw.encode()).hexdigest()

    def _load_snapshot(self, name, allow_stale=True):
        att = self.env["ir.attachment"].sudo().search(
            [("name", "=", name),
             ("res_model", "=", "mrp.purchase.need"),
             ("res_id", "=", 0)], limit=1)
        if not att:
            return None
        try:
            payload = json.loads(
                base64.b64decode(att.datas or b"").decode())
        except Exception:
            return None
        if payload.get("schema") != self._PLAN_SCHEMA:
            return None
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            return None
        # json coerces the int product_id keys to strings
        plan = {int(k): v for k, v in plan.items()}
        if payload.get("v") == self._plan_version():
            return plan
        if allow_stale and time.time() - payload.get("t", 0) \
                < self._PLAN_SNAPSHOT_MAX_AGE:
            return plan
        return None

    def _store_snapshot(self, name, plan):
        try:
            payload = base64.b64encode(json.dumps(
                {"v": self._plan_version(), "t": time.time(),
                 "schema": self._PLAN_SCHEMA,
                 "plan": plan}, default=str).encode())
        except Exception:
            return  # a non-serializable plan must never break requests
        Att = self.env["ir.attachment"].sudo()
        att = Att.search(
            [("name", "=", name),
             ("res_model", "=", "mrp.purchase.need"),
             ("res_id", "=", 0)], limit=1)
        if att:
            att.write({"datas": payload})
        else:
            Att.create({
                "name": name, "type": "binary",
                "res_model": "mrp.purchase.need", "res_id": 0,
                "datas": payload})

    @api.model
    def _cron_plan_warmup(self):
        """Keep the canonical (unfiltered) plan snapshot warm so user
        requests almost never pay the full build — the snapshot serves
        every worker and survives restarts.

        Rebuilds only when the stored snapshot is missing or
        version-stale; that rebuild also runs the MİP record sync that
        request-path builds skip, keeping mip.need.line bookkeeping
        fresh in the background. It additionally keeps rebuilding while
        the MİP-creation backlog flag is set — bulk-loaded datasets get
        their records minted in bounded batches, off the request path."""
        name = self._snapshot_name(False, None, None, "")
        backlog = self.env["ir.config_parameter"].sudo().get_param(
            _MIP_BACKLOG_PARAM, "")
        if not backlog and self._load_snapshot(
                name, allow_stale=False) is not None:
            return
        plan = self._build_plan(False, None, None, "", run_sync=True)
        self._store_snapshot(name, plan)
        with _PLAN_CACHE_LOCK:
            _PLAN_CACHE[self._plan_cache_key(
                False, None, None, "")] = (
                    fields.Datetime.now().timestamp(), plan)

    @api.model
    def _invalidate_plan_cache(self):
        db = self.env.cr.dbname
        with _PLAN_CACHE_LOCK:
            for key in [k for k in _PLAN_CACHE if k[0] == db]:
                _PLAN_CACHE.pop(key, None)

    # ------------------------------------------------------------------
    # plan computation
    # ------------------------------------------------------------------

    @api.model
    def _build_plan(self, warehouse_id, date_from, date_to, query,
                    products=None, _prof=None, run_sync=True):
        """Compute per-product need data — pure dicts, no recordsets.

        Every heavy read is batched into _load_ctx(): moves, picked
        quantities, locations, PO/MO/picking/SO names, UoM factors and
        seller info are fetched once, then the chronological stock walk
        runs in plain Python. The result is serializable so _get_plan can
        cache it between requests (BRD §9).

        Returns {product_id: {product, onhand, end_balance, route, lines,
        suggestions}}.
        """
        _t = [time.monotonic()]

        def _mark(name):
            if _prof is not None:
                _prof[name] = _prof.get(name, 0.0) \
                    + time.monotonic() - _t[0]
                _t[0] = time.monotonic()

        scope_ids = set(self._get_scope_locations(warehouse_id).ids)
        need_moves = self._get_need_moves(
            scope_ids, date_from, date_to, query, products=products)
        if not need_moves:
            return {}
        _mark("scope+need_moves")
        ctx = self._load_ctx(need_moves)
        _mark("load_ctx(need)")
        need_products = need_moves.product_id
        need_set = set(need_moves.ids)
        # durable MİP records are upserted on every plan build so each
        # need row gets a stable number without duplicating on refresh
        mip_cap = (_MIP_ENSURE_CRON if run_sync else _MIP_ENSURE_INLINE)
        mip_by_move, mip_trunc = self._ensure_mip_lines(
            need_moves, ctx, max_create=mip_cap)
        _mark("ensure_mips")
        # BoM explosion graph: components of demanded manufactured
        # products become virtual needs, level by level (depth order so
        # every parent is processed before its components)
        bom_map, children, depth, comp_products = self._get_bom_graph(
            need_products)
        products = need_products | comp_products
        # components with no pending move at all still need their product
        # card (uom, routes, sellers, lead days) in ctx — virtual demand
        # is planned for them even without stock flow
        self._load_products(ctx, products)
        _mark("bom_graph+products")
        flow_moves = self._get_flow_moves(products, scope_ids)
        self._load_ctx(flow_moves, ctx)
        _mark("flow+load_ctx")
        onhand = self._get_onhand(products, scope_ids)
        requested, req_docs, pend = self._get_requested_quantities(
            need_moves, ctx)
        exc_map = self._get_reschedule_log(need_moves)
        _mark("onhand+requested")
        lead_info = self._get_lead_info(products, ctx)
        _mark("lead_info")
        buy_ids = self._get_buy_route_ids()
        manu_ids = self._get_manu_route_ids()
        route_sets = (buy_ids, manu_ids)
        today = fields.Date.context_today(self)

        # need moves are themselves pending outgoing flow — they appear
        # in flow_by_product too (that is what consumes the supply pool)
        flow_by_product = defaultdict(list)
        need_by_product = defaultdict(list)
        for mid in flow_moves.ids:
            mv = ctx["moves"][mid]
            flow_by_product[mv["product_id"]].append(mv)
        for mid in need_moves.ids:
            mv = ctx["moves"][mid]
            need_by_product[mv["product_id"]].append(mv)

        # ---- cheap coverage pre-pass ----------------------------------
        # If a product's total open outbound flow can never exceed
        # onhand + all open inbound supply, it is provably covered in
        # ANY chronology — its walk would only yield hidden fully-covered
        # lines, so it is skipped unless a purchase request is already
        # attached (traceability rows must stay exact).
        inflow_tot = defaultdict(float)
        outflow_tot = defaultdict(float)
        for pid, mvs in flow_by_product.items():
            for mv in mvs:
                if mv["location_dest_id"] in scope_ids \
                        and mv["location_id"] not in scope_ids:
                    inflow_tot[pid] += self._conv(
                        ctx, self._open_qty(ctx, mv),
                        mv["product_uom"],
                        ctx["prod"][pid]["uom_id"])
                elif mv["location_id"] in scope_ids \
                        and mv["location_dest_id"] not in scope_ids:
                    outflow_tot[pid] += self._conv(
                        ctx, self._open_qty(ctx, mv),
                        mv["product_uom"],
                        ctx["prod"][pid]["uom_id"])
        skip_pids = {
            pid for pid in products.ids
            if outflow_tot[pid]
            <= onhand.get(pid, 0.0) + inflow_tot[pid] + 1e-9
            and not any(
                requested.get(mv["id"]) or pend.get(mv["id"])
                for mv in need_by_product[pid])
        }

        _mark("flow_bucket+prepass")

        # ---- phase A: per-product chronological walk + BoM explosion --
        walks = {}
        virtual_events = defaultdict(dict)  # pid -> {key: event dict}
        seen_keys = set()
        ordered = sorted(
            products.ids,
            key=lambda pid: depth.get(
                ctx["prod"][pid]["tmpl_id"], 0))
        for pid in ordered:
            ev_map = virtual_events.pop(pid, {})
            seen_keys.update(ev_map)
            if pid in skip_pids and not ev_map:
                # provably covered: no line survives the hidden filter,
                # no BoM explosion needed (uncovered == 0)
                walks[pid] = {"needs": [], "vevents": []}
                continue
            vevents = list(ev_map.values())
            walk = self._walk_product(
                pid,
                need_by_product[pid],
                flow_by_product[pid],
                onhand.get(pid, 0.0),
                scope_ids,
                need_set,
                vevents,
                ctx,
            )
            walks[pid] = walk
            if walk["needs"]:
                self._explode_bom(
                    pid, walk, bom_map, manu_ids, ctx,
                    out=virtual_events)
        _mark("walks+explosion")

        # ---- virtual MİP records + live request links, in one batch ---
        all_vevents = [
            ev for w in walks.values() for ev in w["vevents"]]
        vmips, vmip_trunc = self._ensure_virtual_mips(
            all_vevents, max_create=mip_cap)
        demand = {ev["key"]: ev["qty"] for ev in all_vevents}
        vreq, _vdocs, vpend = self._get_virtual_requested(
            demand, vmips, ctx)
        _mark("virtual_mips")

        # ---- phase B: suggestions + serializable lines ----------------
        plan = {}
        for pid in ordered:
            walk = walks[pid]
            if not walk["needs"]:
                continue
            data = self._finalize_product(
                pid, walk, ctx, mip_by_move, requested, req_docs, pend,
                vmips, vreq, vpend, exc_map,
                lead_info[pid], today, route_sets)
            if data["lines"]:
                plan[pid] = data
        _mark("finalize")

        # ---- MİP bookkeeping (bulk, diff-only writes) ----------------
        # skipped on the request path (run_sync=False) — mip.need.line
        # history rows are refreshed by the warm-up cron; the plan
        # payload itself is complete without them
        if run_sync:
            self._sync_mips(mip_by_move, ctx)
            virt_lines = {
                ln["key"]: ln
                for data in plan.values() for ln in data["lines"]
                if ln["virtual"]}
            self._sync_virtual_mips(vmips, virt_lines)
            # virtual needs that vanished from the plan close their MİP
            # records — the history stays queryable (BRD §4.3). Only the
            # canonical unfiltered build may close records: a query- or
            # date-scoped plan legitimately lacks events whose needs
            # still exist outside the filter window (warehouse filtering
            # is safe because the close domain itself is
            # warehouse-scoped).
            if not query and not date_from and not date_to:
                self._close_stale_virtual_mips(seen_keys, warehouse_id)
        # only canonical builds own the backlog flag — a capped ensure
        # tells the warm-up cron to keep rebuilding until every need row
        # has its durable MİP record (bulk-load cold start)
        if not query and not date_from and not date_to:
            self.env["ir.config_parameter"].sudo().set_param(
                _MIP_BACKLOG_PARAM,
                "1" if (mip_trunc or vmip_trunc) else "")
        _mark("mip_sync")
        return plan

    @api.model
    def plan_profile(self):
        """Diagnostic RPC entrypoint: run a canonical build and return
        per-phase timings — used to locate hotspots on real data."""
        prof = {}
        t = time.monotonic()
        plan = self._build_plan(
            False, None, None, "", _prof=prof, run_sync=False)
        prof["total"] = time.monotonic() - t
        prof["products"] = len(plan)
        prof["lines"] = sum(len(d["lines"]) for d in plan.values())
        return prof

    # ------------------------------------------------------------------
    # bulk data loading — everything the walk needs, in a handful of
    # queries instead of per-record attribute access
    # ------------------------------------------------------------------

    @api.model
    def _load_ctx(self, moves, ctx=None):
        """Bulk-read move rows and every lookup table they reference.

        Returns a ctx dict:
          moves     {move_id: dict}
          picked    {move_id: picked qty in move uom}
          loc_usage / loc_name / loc_company
          prod      {pid: dict(uom_id, uom_name, name, default_code,
                     display_name, tmpl_id, routes:set, produce_delay,
                     proc_days, standard_price)}
          po_line   {plid: dict(order_id, product_qty, qty_received,
                     uom, date_planned)}
          po        {oid: dict(name, partner, state, date_planned)}
          mo_name / pick_name / so_name / partner_name
          uom_factor / uom_name / uom_cat
          sellers   {pid: [seller dicts]}
        """
        if ctx is None:
            ctx = {
                "moves": {}, "picked": defaultdict(float),
                "loc_usage": {}, "loc_name": {}, "loc_company": {},
                "prod": {},
                "po_line": {}, "po": {},
                "mo_name": {}, "pick_name": {}, "so_name": {},
                "sl_order": {}, "partner_name": {},
                "uom_factor": {}, "uom_name": {}, "uom_cat": {},
                "uom_all": False, "user_name": {},
                "sellers": defaultdict(list),
                "tz": timezone(self.env.user.tz or "UTC"),
            }
        if not moves:
            return ctx
        fields_list = list(_MOVE_FIELDS)
        has_sale = "sale_line_id" in self.env["stock.move"]._fields
        if has_sale:
            fields_list.append("sale_line_id")
        loc_ids, prod_ids, pl_ids = set(), set(), set()
        mo_ids, pick_ids, sl_ids, uom_ids = set(), set(), set(), set()
        for d in moves.read(fields_list, load="_classic_write"):
            mid = d["id"]
            # read() may yield ISO strings for datetimes depending on the
            # serialization path — normalize once so every comparison
            # and timezone conversion downstream sees real datetimes
            d["date"] = fields.Datetime.to_datetime(d["date"])
            d["date_deadline"] = fields.Datetime.to_datetime(
                d["date_deadline"])
            ctx["moves"][mid] = d
            prod_ids.add(d["product_id"])
            loc_ids.add(d["location_id"])
            loc_ids.add(d["location_dest_id"])
            uom_ids.add(d["product_uom"])
            if d.get("purchase_line_id"):
                pl_ids.add(d["purchase_line_id"])
            if d.get("production_id"):
                mo_ids.add(d["production_id"])
            if d.get("raw_material_production_id"):
                mo_ids.add(d["raw_material_production_id"])
            if d.get("picking_id"):
                pick_ids.add(d["picking_id"])
            if has_sale and d.get("sale_line_id"):
                sl_ids.add(d["sale_line_id"])

        # picked quantities — picked move lines reduce the open demand
        picked_rows = self.env["stock.move.line"].sudo().search_read(
            [("move_id", "in", moves.ids), ("picked", "=", True)],
            ["move_id", "quantity", "product_uom_id"],
            load="_classic_write")
        for d in picked_rows:
            uom_ids.add(d["product_uom_id"])
        self._load_uoms(ctx, uom_ids)
        for d in picked_rows:
            src = d["product_uom_id"]
            dst = ctx["moves"][d["move_id"]]["product_uom"]
            ctx["picked"][d["move_id"]] += self._conv(
                ctx, d["quantity"], src, dst)

        # locations — usage decides supply vs demand, name/company the
        # displayed row metadata
        for d in self.env["stock.location"].sudo().browse(
                loc_ids).read(["usage", "display_name", "company_id"],
                              load="_classic_write"):
            ctx["loc_usage"][d["id"]] = d["usage"]
            ctx["loc_name"][d["id"]] = d["display_name"]
            ctx["loc_company"][d["id"]] = d.get("company_id") or False

        # products — one read for every field the plan consults
        prods = self.env["product.product"].browse(prod_ids)
        prod_rows = prods.read([
            "display_name", "default_code", "uom_id", "product_tmpl_id",
            "route_ids", "produce_delay", "x_purchase_process_days",
            "standard_price", "x_mip_responsible_id",
            "x_sa_responsible_id",
        ], load="_classic_write")
        tmpl_ids = set()
        user_ids = set()
        for d in prod_rows:
            uom_ids.add(d["uom_id"])
            tmpl_ids.add(d["product_tmpl_id"])
            if d["x_mip_responsible_id"]:
                user_ids.add(d["x_mip_responsible_id"])
            if d["x_sa_responsible_id"]:
                user_ids.add(d["x_sa_responsible_id"])
        for d in prod_rows:
            ctx["prod"][d["id"]] = {
                "id": d["id"],
                "display_name": d["display_name"],
                "default_code": d["default_code"] or "",
                "uom_id": d["uom_id"],
                "uom_name": "",  # filled once uoms are loaded
                "tmpl_id": d["product_tmpl_id"],
                "routes": set(d["route_ids"]),
                "produce_delay": d["produce_delay"] or 0,
                "proc_days": d["x_purchase_process_days"] or 0,
                "standard_price": d["standard_price"] or 0.0,
                "mip_resp_id": d["x_mip_responsible_id"] or False,
                "sa_resp_id": d["x_sa_responsible_id"] or False,
            }
        self._load_uoms(ctx, uom_ids)
        self._load_users(ctx, user_ids)
        for d in ctx["prod"].values():
            d["uom_name"] = ctx["uom_name"].get(d["uom_id"], "")
            d["mip_resp"] = ctx["user_name"].get(d["mip_resp_id"], "")
            d["sa_resp"] = ctx["user_name"].get(d["sa_resp_id"], "")

        # purchase lines + their orders (supply attribution, suggestions)
        if pl_ids:
            order_ids = set()
            pol = self.env["purchase.order.line"].sudo().browse(pl_ids)
            for d in pol.read([
                    "order_id", "product_qty", "qty_received",
                    "product_uom_id", "date_planned"],
                    load="_classic_write"):
                ctx["po_line"][d["id"]] = d
                order_ids.add(d["order_id"])
                uom_ids.add(d["product_uom_id"])
            po = self.env["purchase.order"].sudo().browse(order_ids)
            partner_ids = set()
            for d in po.read(["name", "partner_id", "state",
                              "date_planned", "date_approve"],
                             load="_classic_write"):
                ctx["po"][d["id"]] = d
                if d["partner_id"]:
                    partner_ids.add(d["partner_id"])
            self._load_partners(ctx, partner_ids)
            self._load_uoms(ctx, uom_ids)

        # MO / picking / SO display names for the source column
        if mo_ids:
            for d in self.env["mrp.production"].sudo().browse(
                    mo_ids).read(["name"], load="_classic_write"):
                ctx["mo_name"][d["id"]] = d["name"]
        if pick_ids:
            for d in self.env["stock.picking"].sudo().browse(
                    pick_ids).read(["name"], load="_classic_write"):
                ctx["pick_name"][d["id"]] = d["name"]
        if sl_ids:
            sl_rows = self.env["sale.order.line"].sudo().browse(
                sl_ids).read(["order_id"], load="_classic_write")
            ctx["sl_order"] = {d["id"]: d["order_id"] for d in sl_rows}
            order_ids = {d["order_id"] for d in sl_rows}
            for d in self.env["sale.order"].sudo().browse(
                    order_ids).read(["name"], load="_classic_write"):
                ctx["so_name"][d["id"]] = d["name"]

        # seller lookup used for the purchase lead time of each line —
        # mirrors product._select_seller without per-line ORM calls
        self._load_sellers(ctx, prod_ids, tmpl_ids)
        return ctx

    @api.model
    def _load_products(self, ctx, products):
        """Fill ctx["prod"] (+ uom names + seller rows) for products that
        did not appear in any move read — e.g. BoM components whose only
        demand is the virtual need this plan is about to create."""
        missing = [pid for pid in products.ids if pid not in ctx["prod"]]
        if not missing:
            return
        uom_ids = set()
        rows = self.env["product.product"].browse(missing).read([
            "display_name", "default_code", "uom_id", "product_tmpl_id",
            "route_ids", "produce_delay", "x_purchase_process_days",
            "standard_price", "x_mip_responsible_id",
            "x_sa_responsible_id",
        ], load="_classic_write")
        user_ids = set()
        for d in rows:
            uom_ids.add(d["uom_id"])
            if d["x_mip_responsible_id"]:
                user_ids.add(d["x_mip_responsible_id"])
            if d["x_sa_responsible_id"]:
                user_ids.add(d["x_sa_responsible_id"])
        self._load_uoms(ctx, uom_ids)
        self._load_users(ctx, user_ids)
        tmpl_ids = set()
        for d in rows:
            tmpl_ids.add(d["product_tmpl_id"])
            ctx["prod"][d["id"]] = {
                "id": d["id"],
                "display_name": d["display_name"],
                "default_code": d["default_code"] or "",
                "uom_id": d["uom_id"],
                "uom_name": ctx["uom_name"].get(d["uom_id"], ""),
                "tmpl_id": d["product_tmpl_id"],
                "routes": set(d["route_ids"]),
                "produce_delay": d["produce_delay"] or 0,
                "proc_days": d["x_purchase_process_days"] or 0,
                "standard_price": d["standard_price"] or 0.0,
                "mip_resp_id": d["x_mip_responsible_id"] or False,
                "sa_resp_id": d["x_sa_responsible_id"] or False,
                "mip_resp": ctx["user_name"].get(
                    d["x_mip_responsible_id"], ""),
                "sa_resp": ctx["user_name"].get(
                    d["x_sa_responsible_id"], ""),
            }
        self._load_sellers(ctx, missing, tmpl_ids)

    @api.model
    def _load_sellers(self, ctx, prod_ids, tmpl_ids):
        """Load vendor rows used for per-line purchase lead time —
        mirrors product._select_seller without per-line ORM calls."""
        seller_rows = self.env["product.supplierinfo"].sudo().search_read(
            ["|", ("product_id", "in", list(prod_ids)),
             ("product_tmpl_id", "in", list(tmpl_ids))],
            ["product_id", "product_tmpl_id", "partner_id", "delay",
             "min_qty", "sequence", "price", "company_id",
             "date_start", "date_end"],
            load="_classic_write")
        for d in seller_rows:
            d["date_start"] = fields.Date.to_date(d["date_start"])
            d["date_end"] = fields.Date.to_date(d["date_end"])
        tmpl_of = {pid: ctx["prod"][pid]["tmpl_id"]
                   for pid in ctx["prod"]}
        for d in seller_rows:
            pids = []
            if d["product_id"]:
                pids = [d["product_id"]]
            elif d["product_tmpl_id"]:
                pids = [pid for pid, t in tmpl_of.items()
                        if t == d["product_tmpl_id"]]
            for pid in pids:
                if pid in ctx["prod"]:
                    ctx["sellers"][pid].append(d)
        for rows in ctx["sellers"].values():
            rows.sort(key=lambda s: (
                s["sequence"], -(s["min_qty"] or 0.0),
                s["price"] or 0.0, s["id"]))

    @api.model
    def _load_uoms(self, ctx, uom_ids):
        if ctx["uom_all"]:
            return
        ctx["uom_all"] = True
        # Odoo 19 has no uom categories: units link to a reference unit
        # via relative_uom_id/relative_factor ("contains N reference").
        # The table is tiny — resolve every unit's base factor and its
        # chain root (used as the "same family" guard for _conv).
        rows = self.env["uom.uom"].sudo().search_read(
            [], ["name", "relative_uom_id", "relative_factor"],
            load="_classic_write")
        by_id = {d["id"]: d for d in rows}
        for d in rows:
            base, root, cur, seen = (
                d["relative_factor"] or 1.0), d["id"], d, set()
            while cur["relative_uom_id"] and cur["id"] not in seen:
                seen.add(cur["id"])
                cur = by_id.get(cur["relative_uom_id"])
                if not cur:
                    break
                base *= cur["relative_factor"] or 1.0
                root = cur["id"]
            # store the inverse so _conv keeps the classic
            # qty * f[dst] / f[src] form
            ctx["uom_factor"][d["id"]] = 1.0 / base if base else 1.0
            ctx["uom_name"][d["id"]] = d["name"]
            ctx["uom_cat"][d["id"]] = root
        for i in uom_ids:
            ctx["uom_factor"].setdefault(i, 1.0)
            ctx["uom_name"].setdefault(i, str(i))
            ctx["uom_cat"].setdefault(i, i)

    @api.model
    def _load_users(self, ctx, user_ids):
        missing = [i for i in user_ids if i not in ctx["user_name"]]
        if not missing:
            return
        rows = self.env["res.users"].sudo().browse(missing).read(
            ["name"], load="_classic_write")
        for d in rows:
            ctx["user_name"][d["id"]] = d["name"]

    @api.model
    def _load_partners(self, ctx, partner_ids):
        missing = [i for i in partner_ids if i not in ctx["partner_name"]]
        if not missing:
            return
        rows = self.env["res.partner"].sudo().browse(missing).read(
            ["display_name"], load="_classic_write")
        for d in rows:
            ctx["partner_name"][d["id"]] = d["display_name"]

    @api.model
    def _conv(self, ctx, qty, src_uom, dst_uom):
        """UoM conversion via cached factors (same category only)."""
        if not src_uom or not dst_uom or src_uom == dst_uom:
            return qty
        if ctx["uom_cat"].get(src_uom) != ctx["uom_cat"].get(dst_uom):
            return qty
        return qty * ctx["uom_factor"][dst_uom] \
            / ctx["uom_factor"][src_uom]

    @api.model
    def _open_qty(self, ctx, mv):
        """Remaining move demand in the move's own UoM."""
        return mv["product_uom_qty"] - ctx["picked"].get(mv["id"], 0.0)

    @api.model
    def _move_open_qty(self, move):
        """Remaining move demand in the move's UoM — ORM variant used by
        mip.need.line._sync_from_moves (cron path, recordset input).

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
    def _seller_delay(self, ctx, pid, qty, date):
        """Lead days of the best-matching vendor — mirrors
        product._select_seller (sequence, min_qty, date validity,
        company) without per-line ORM calls."""
        today = fields.Date.context_today(self)
        ref = date or today
        company_ids = set(self.env.companies.ids)
        best = None
        for s in ctx["sellers"].get(pid, ()):
            if s["company_id"] and s["company_id"] not in company_ids:
                continue
            if s["min_qty"] and s["min_qty"] > qty:
                continue
            if s["date_start"] and s["date_start"] > ref:
                continue
            if s["date_end"] and s["date_end"] < ref:
                continue
            best = s
            break  # sellers list is already preference-sorted
        return best["delay"] if best else 0

    # ------------------------------------------------------------------
    # phase A — chronological stock walk per product
    # ------------------------------------------------------------------

    @api.model
    def _walk_product(self, pid, need_moves, flow_moves, onhand,
                      scope_ids, need_set, vevents, ctx):
        """Chronological stock walk for one product — pure data.

        Incoming and outgoing pending moves are applied in date order —
        receipts before issues on the same day. ``detail`` keeps the
        running balance right after each need's consumption (forecast)
        and the incremental shortage it introduces (uncovered, BRD §6.2).
        """
        need_ids = {mv["id"] for mv in need_moves}
        events = []
        for mv in flow_moves:
            src_in = mv["location_id"] in scope_ids
            dst_in = mv["location_dest_id"] in scope_ids
            if src_in == dst_in:
                # either fully outside the scope or an internal transfer
                # inside it — neither changes the scoped balance
                continue
            qty = self._conv(
                ctx, self._open_qty(ctx, mv), mv["product_uom"],
                ctx["prod"][pid]["uom_id"])
            # day-level chronology — the time-of-day must not decide
            # whether a receipt lands "late": a delivery due on the same
            # day as the need covers it
            mv_dt = self._need_dt(mv) if mv["id"] in need_set \
                else mv["date"]
            events.append((self._local_date(
                mv_dt or fields.Datetime.now(), ctx),
                not src_in, ("mv", mv["id"]), qty, mv))
        for ev in vevents:
            events.append((ev["date"], False, ("ev", ev["key"]),
                           ev["qty"], ev))
        # receipts are applied before issues on the same date
        events.sort(key=lambda e: (e[0], 0 if e[1] else 1, str(e[2][1])))

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
                "move_id": False,
                "orig_qty": onhand,
                "qty": onhand,
                "uom": ctx["prod"][pid]["uom_name"],
            })
        pool_idx = 0  # first chunk that may still hold quantity
        need_keys = need_ids | {ev["key"] for ev in vevents}
        for _date, incoming, (_kind, eid), qty, mv in events:
            prev_deficit = deficit
            balance = balance + qty if incoming else balance - qty
            deficit = max(0.0, -balance)
            if incoming:
                pool.append(self._supply_chunk(ctx, mv, qty, pid))
                absorbed = prev_deficit - deficit
                if absorbed > 0.0:
                    late_supplies.append((mv, qty, absorbed))
            else:
                remaining_out = qty
                covers = []
                # walk the pool from the first non-empty chunk — zeroed
                # chunks are skipped once via the moving cursor so a hot
                # product never rescans its whole supply history
                while remaining_out > 0.0 and pool_idx < len(pool):
                    chunk = pool[pool_idx]
                    take = min(chunk["qty"], remaining_out)
                    if take <= 0.0:
                        pool_idx += 1
                        continue
                    chunk["qty"] -= take
                    remaining_out -= take
                    cover = dict(chunk)
                    cover["qty"] = take
                    covers.append(cover)
                    if chunk["qty"] <= 0.0:
                        pool_idx += 1
                if eid in need_keys:
                    # the part of the new shortage this need is
                    # responsible for
                    uncovered = min(qty, max(0.0, deficit - prev_deficit))
                    detail[eid] = {
                        "forecast": balance,
                        "uncovered": uncovered,
                    }
                    coverage_map[eid] = covers

        # needs in chronological order — real moves and virtual events
        ordered_needs = sorted(
            [("mv", mv) for mv in need_moves]
            + [("ev", ev) for ev in vevents],
            key=lambda item: (
                item[1]["date"] if item[0] == "ev"
                else self._local_date(self._need_dt(item[1]), ctx),
                item[1]["key"] if item[0] == "ev" else str(item[1]["id"]),
            ))
        return {
            "detail": detail,
            "coverage_map": coverage_map,
            "late_supplies": late_supplies,
            "pool": pool,
            "balance": balance,
            "onhand": onhand,
            "needs": ordered_needs,
            "vevents": vevents,
        }

    # ------------------------------------------------------------------
    # phase B — suggestions + serializable lines
    # ------------------------------------------------------------------

    @api.model
    def _finalize_product(self, pid, walk, ctx, mip_by_move, requested,
                          req_docs, pend, vmips, vreq, vpend, exc_map,
                          lead, today, route_sets):
        """Turn a phase-A walk into the screen payload for one product."""
        prod = ctx["prod"][pid]
        detail = walk["detail"]
        ordered_needs = walk["needs"]
        buy_ids, manu_ids = route_sets
        product_routes = prod["routes"]
        parts = []
        if buy_ids & product_routes:
            parts.append("S")
        if manu_ids & product_routes:
            parts.append("Ü")
        route_abbr = "+".join(parts) or "-"

        def req_of(kind, entry):
            if kind == "ev":
                return vreq.get(entry["key"], 0.0)
            return requested.get(entry["id"], 0.0)

        def eid_of(kind, entry):
            return entry["key"] if kind == "ev" else entry["id"]

        # Late supply that lands while a shortage exists could still
        # serve earlier uncovered needs if it were pulled forward —
        # informational only (BRD: never reschedule automatically).
        suggest_map = defaultdict(float)
        suggestions = []
        for mv, qty, absorbed in walk["late_supplies"]:
            supply_date = self._local_date(mv["date"], ctx)
            remaining = absorbed
            covers = []
            for kind, nmv in ordered_needs:
                if remaining <= 0.0:
                    break
                need_date = (nmv["date"] if kind == "ev"
                             else self._local_date(
                                 self._need_dt(nmv), ctx))
                neid = eid_of(kind, nmv)
                if need_date >= supply_date or neid not in detail:
                    continue
                open_need = (
                    detail[neid]["uncovered"]
                    - suggest_map[neid]
                    - req_of(kind, nmv))
                if open_need <= 0.0:
                    continue
                covered = min(open_need, remaining)
                suggest_map[neid] += covered
                remaining -= covered
                covers.append((need_date, covered))
            pl = ctx["po_line"].get(mv["purchase_line_id"] or 0)
            order = ctx["po"].get(pl["order_id"]) if pl else None
            if order and order["state"] == "purchase" and covers:
                suggested = min(c[0] for c in covers)
                suggestions.append({
                    "kind": "pull",
                    "move_id": mv["id"],
                    "order_id": order["id"],
                    "order": order["name"],
                    "partner": ctx["partner_name"].get(
                        order["partner_id"], ""),
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
        # A receipt that could still serve needs when pulled forward
        # keeps that suggestion exclusively — never both on one order.
        pull_move_ids = {sug["move_id"] for sug in suggestions}
        for chunk in walk["pool"]:
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
        for kind, entry in ordered_needs:
            if kind == "ev":
                # virtual (BoM-exploded) component need
                need_date = entry["date"]
                delay = self._seller_delay(
                    ctx, pid, entry["qty"], need_date)
                approve_by = need_date - timedelta(days=delay)
                purchase_start = approve_by - timedelta(days=lead["proc"])
                info = detail.get(
                    entry["key"], {"forecast": walk["balance"],
                                   "uncovered": 0.0})
                req_qty = vreq.get(entry["key"], 0.0)
                requestable = max(0.0, info["uncovered"] - req_qty)
                mip = vmips.get(entry["key"])
                lines.append({
                    "key": entry["key"],
                    "move_id": False,
                    "virtual": True,
                    "mip_id": mip["id"] if mip else False,
                    "mip_name": mip["name"] if mip else "",
                    # virtual needs have no source document — the MİP
                    # record itself is the deepest reachable card
                    "doc_model": "mip.need.line" if mip else "",
                    "doc_id": mip["id"] if mip else False,
                    "company_id": entry["company_id"],
                    "warehouse_id": entry["warehouse_id"],
                    "need_date": fields.Date.to_string(need_date),
                    "location": entry["location"],
                    "route": route_abbr,
                    "source": " / ".join(sorted(entry["parents"]))
                        or self.env._("Üretim Planı"),
                    "source_type": "ÜP",
                    "onhand": walk["onhand"],
                    "forecast": info["forecast"],
                    "need_qty": entry["qty"],
                    "uncovered_qty": info["uncovered"],
                    "covered_qty": entry["qty"] - info["uncovered"],
                    "coverage": walk["coverage_map"].get(entry["key"], []),
                    "pending": vpend.get(entry["key"], []),
                    "pull_covered": suggest_map[entry["key"]],
                    "uom": prod["uom_name"],
                    "approve_by": fields.Date.to_string(approve_by),
                    "purchase_start": fields.Date.to_string(purchase_start),
                    "is_late": purchase_start < today,
                    "suggested_termin": fields.Date.to_string(
                        self._suggested_termin(
                            ctx, need_date, delay, today,
                            walk["coverage_map"].get(entry["key"], []),
                            vpend.get(entry["key"], []), requestable)),
                    "exception": False,
                    "exception_log": [],
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
            mv = entry
            qty = self._conv(
                ctx, self._open_qty(ctx, mv), mv["product_uom"],
                prod["uom_id"])
            # MO components are needed when production is scheduled to
            # consume them (move.date); customer deliveries are needed by
            # the promised ship date (date_deadline, falling back to the
            # scheduled date)
            need_dt = self._need_dt(mv)
            if mv["raw_material_production_id"]:
                source = ctx["mo_name"].get(
                    mv["raw_material_production_id"], "")
                source_type = "MO"
            else:
                source_type = "SO" if ctx["loc_usage"].get(
                    mv["location_dest_id"]) == "customer" else "-"
                sl = mv.get("sale_line_id")
                if sl and ctx["so_name"].get(ctx["sl_order"].get(sl)):
                    source = ctx["so_name"][ctx["sl_order"][sl]]
                else:
                    source = mv["origin"] or ctx["pick_name"].get(
                        mv["picking_id"], "")
            need_date = self._local_date(need_dt, ctx)
            delay = self._seller_delay(ctx, pid, qty, need_date)
            approve_by = need_date - timedelta(days=delay)
            purchase_start = approve_by - timedelta(days=lead["proc"])
            info = detail.get(mv["id"], {"forecast": walk["balance"],
                                         "uncovered": 0.0})
            req_qty = requested.get(mv["id"], 0.0)
            requestable = max(0.0, info["uncovered"] - req_qty)
            # informational exception flag: linked request/RFQ/PO is no
            # longer (fully) needed — nothing is cancelled automatically
            action, action_doc = "", ""
            if req_qty > 0.0 and info["uncovered"] <= 0.0:
                action = self.env._("İşlemi iptal et")
            elif req_qty > info["uncovered"]:
                action = self.env._("Miktarı azalt")
            elif suggest_map[mv["id"]] > 0.0:
                action = self.env._("İşlemi öne al")
            elif 0.0 < req_qty < info["uncovered"]:
                # part of the need already has a request; the remainder
                # can be added to it
                action = self.env._("Miktarı arttır")
            if action == self.env._("İşlemi öne al"):
                # a pull-forward always points at a confirmed PO
                action_doc = self.env._("Onaylı Sipariş")
            elif action:
                labels = sorted(req_docs.get(mv["id"], ()), reverse=True)
                action_doc = " / ".join(dict.fromkeys(
                    label for _prio, label in labels))
            mip = mip_by_move.get(mv["id"], {})
            lines.append({
                "key": "mv:%s" % mv["id"],
                "move_id": mv["id"],
                "virtual": False,
                "mip_id": mip.get("id") or False,
                "mip_name": mip.get("name") or "",
                # the MİP number opens the operational master document:
                # MO > transfer > sale order — a need with none of them
                # has no real source record, so it stays plain text
                "doc_model": (
                    "mrp.production"
                    if mv["raw_material_production_id"]
                    else "stock.picking" if mv["picking_id"]
                    else "sale.order"
                    if mv.get("sale_line_id")
                    and ctx["sl_order"].get(mv["sale_line_id"])
                    else ""),
                "doc_id": (
                    mv["raw_material_production_id"] or mv["picking_id"]
                    or ctx["sl_order"].get(mv.get("sale_line_id"))
                    or False),
                "company_id": mv["company_id"],
                "warehouse_id": mv["warehouse_id"],
                "need_date": fields.Date.to_string(need_date),
                "location": ctx["loc_name"].get(mv["location_id"], ""),
                "route": route_abbr,
                "source": source,
                "source_type": source_type,
                "onhand": walk["onhand"],
                "forecast": info["forecast"],
                "need_qty": qty,
                "uncovered_qty": info["uncovered"],
                "covered_qty": qty - info["uncovered"],
                "coverage": walk["coverage_map"].get(mv["id"], []),
                "pending": pend.get(mv["id"], []),
                "pull_covered": suggest_map[mv["id"]],
                "uom": prod["uom_name"],
                "approve_by": fields.Date.to_string(approve_by),
                "purchase_start": fields.Date.to_string(purchase_start),
                "is_late": purchase_start < today,
                "suggested_termin": fields.Date.to_string(
                    self._suggested_termin(
                        ctx, need_date, delay, today,
                        walk["coverage_map"].get(mv["id"], []),
                        pend.get(mv["id"], []), requestable)),
                "exception": bool(exc_map.get(mv["id"])),
                "exception_log": exc_map.get(mv["id"], []),
                "requested_qty": req_qty,
                "requestable_qty": requestable,
                "action": action,
                "action_doc": action_doc,
                "already_requested":
                    req_qty > 0.0 and requestable <= 0.0,
                "can_buy": bool(buy_ids & product_routes),
                "missing_lead_config": lead["missing"],
            })
        return {
            "product": prod,
            "onhand": walk["onhand"],
            "end_balance": walk["balance"],
            "route": route_abbr,
            "lines": lines,
            "suggestions": suggestions,
        }

    @api.model
    def _group_payload(self, data):
        product = data["product"]
        lines = data["lines"]
        starts = [ln["purchase_start"] for ln in lines]
        locs = list(dict.fromkeys(ln["location"] for ln in lines))
        return {
            "product_id": product["id"],
            "name": product["display_name"],
            "code": product["default_code"],
            "uom": product["uom_name"],
            "mip_resp": product.get("mip_resp", ""),
            "sa_resp": product.get("sa_resp", ""),
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
            "earliest_termin": min(
                (ln["suggested_termin"] for ln in lines
                 if ln.get("suggested_termin")), default=""),
            "has_late": any(
                ln["is_late"] and ln["requestable_qty"] > 0
                for ln in lines),
            "missing_lead_config": any(
                ln["missing_lead_config"] for ln in lines),
            "requested_count": sum(
                1 for ln in lines if ln["requested_qty"] > 0),
            "suggestion_count": len(data.get("suggestions") or []),
            "exception_count": sum(
                1 for ln in lines if ln.get("exception")),
        }

    # ------------------------------------------------------------------
    # small helpers working on move dicts
    # ------------------------------------------------------------------

    @api.model
    def _suggested_termin(self, ctx, need_date, delay, today, coverage,
                          pending, requestable):
        """Realistic delivery date when the need can no longer arrive on
        its planned date — empty while the plan is still feasible.

        Every still-unapproved source (open remainder, draft/approved
        requests, unconfirmed RFQs) can at best be approved today; a
        confirmed PO is bound by its own approval date. The latest
        feasible arrival is approval_base + supplier lead time, and it
        only matters when that lands after the need date."""
        bases = []
        if requestable > 0.0:
            bases.append(today)
        if pending:
            # listed docs are exactly the unconfirmed ones — their
            # approval is still ahead, so today is the earliest base
            bases.append(today)
        for chunk in coverage or []:
            if chunk.get("kind") == "po":
                appr = (ctx["po"].get(chunk.get("order_id") or 0) or {}
                        ).get("date_approve")
                if appr:
                    bases.append(self._local_date(appr, ctx))
        if not bases:
            return False
        sug = max(bases) + timedelta(days=delay)
        return sug if sug > need_date else False

    @api.model
    def _local_date(self, dt, ctx=None):
        """User-timezone date of a datetime — plain Date.to_date would
        truncate the UTC value and show the previous day for
        local-midnight dates."""
        if not dt:
            return None
        dt = fields.Datetime.to_datetime(dt)
        if ctx is not None:
            return utc.localize(dt).astimezone(ctx["tz"]).date()
        return fields.Datetime.context_timestamp(self, dt).date()

    @api.model
    def _supply_chunk(self, ctx, mv, qty, pid):
        """One consumable supply unit for the FIFO coverage pool — a PO
        receipt, an MO output or any other expected receipt."""
        pl = ctx["po_line"].get(mv["purchase_line_id"] or 0)
        kind, name, order_id, partner = "other", "", False, ""
        if pl:
            order = ctx["po"].get(pl["order_id"], {})
            kind, order_id = "po", pl["order_id"]
            name = order.get("name", "")
            partner = ctx["partner_name"].get(order.get("partner_id"), "")
        elif mv["production_id"]:
            kind = "mo"
            name = ctx["mo_name"].get(mv["production_id"], "")
        else:
            name = mv["origin"] or ctx["pick_name"].get(
                mv["picking_id"], self.env._("Beklenen tedarik"))
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
            "date": fields.Date.to_string(
                self._local_date(mv["date"], ctx)),
            "order_id": order_id,
            "move_id": mv["id"],
            "orig_qty": qty,
            "qty": qty,
            "uom": ctx["prod"][pid]["uom_name"],
        }

    @api.model
    def _need_dt(self, mv):
        """Planning date of a need move — components consume at the
        scheduled date, deliveries by the promised date (falls back to
        the scheduled date). Accepts both a move dict (plan path) and a
        stock.move record (cron/MİP sync path)."""
        if isinstance(mv, dict):
            if mv["raw_material_production_id"]:
                return mv["date"]
            return mv["date_deadline"] or mv["date"]
        if mv.raw_material_production_id:
            return mv.date
        return mv.date_deadline or mv.date

    # ------------------------------------------------------------------
    # MİP persistence
    # ------------------------------------------------------------------

    @api.model
    def _ensure_mip_lines(self, need_moves, ctx=None, max_create=None):
        """Create the persistent MİP record of every need move
        (BRD §4.1/§4.3). Returns ({move_id: {id, name, rec}}, truncated).

        Records are keyed by move and the number is assigned once, so
        refreshes and re-computations never mint duplicates. Syncing is
        done once per build in bulk by _sync_mips — not per record.

        ``max_create`` bounds the records created in one call: bulk
        loads (migration, mass import) must not blow the request-time
        limit — the warm-up cron drains the rest in batches."""
        if ctx is None:
            ctx = self._load_ctx(need_moves)
        Mip = self.env["mip.need.line"].sudo()
        existing = Mip.search_read(
            [("move_id", "in", need_moves.ids)], ["move_id", "name"],
            load="_classic_write")
        by_move = {}
        missing_ids = set(need_moves.ids)
        for d in existing:
            by_move[d["move_id"]] = {
                "id": d["id"], "name": d["name"],
                "rec": Mip.browse(d["id"]),
            }
            missing_ids.discard(d["move_id"])
        truncated = False
        if missing_ids:
            missing_ids = sorted(missing_ids)
            if max_create is not None and len(missing_ids) > max_create:
                missing_ids = missing_ids[:max_create]
                truncated = True
            missing_ids = set(missing_ids)
        if missing_ids:
            vals_list = []
            for mid in missing_ids:
                mv = ctx["moves"][mid]
                prod = ctx["prod"][mv["product_id"]]
                cur = self._conv(
                    ctx, mv["product_uom_qty"], mv["product_uom"],
                    prod["uom_id"])
                open_qty = self._conv(
                    ctx, self._open_qty(ctx, mv), mv["product_uom"],
                    prod["uom_id"])
                covered = max(0.0, cur - open_qty)
                # quantity/state are written at create so _sync_mips
                # never rewrites freshly minted records — a mass mint
                # followed by a mass update is what used to crush the
                # warm-up cron's transaction
                vals_list.append({
                    "key": "mv:%s" % mid,
                    "move_id": mid,
                    "product_id": mv["product_id"],
                    "company_id": mv["company_id"],
                    "warehouse_id": mv["warehouse_id"],
                    "location_id": mv["location_id"],
                    "need_date": self._local_date(
                        self._need_dt(mv), ctx),
                    "source_type":
                        "mo" if mv["raw_material_production_id"]
                        else "so" if ctx["loc_usage"].get(
                            mv["location_dest_id"]) == "customer"
                        else "other",
                    "production_id": mv["raw_material_production_id"]
                        or False,
                    "uom_id": prod["uom_id"],
                    "initial_qty": cur,
                    "current_qty": cur,
                    "covered_qty": covered,
                    "remaining_qty": open_qty,
                    "state": ("open" if covered <= 0.0
                              else "done" if covered >= cur
                              else "partial"),
                })
            vals_list.sort(key=lambda v: v["move_id"])
            for i in range(0, len(vals_list), _MIP_CHUNK):
                created = Mip.create(vals_list[i:i + _MIP_CHUNK])
                for rec in created:
                    by_move[rec.move_id.id] = {
                        "id": rec.id, "name": rec.name, "rec": rec,
                        "new": True}
        return by_move, truncated

    @api.model
    def _sync_mips(self, mip_by_move, ctx):
        """Bulk MİP refresh computed from the move dicts already in ctx —
        one pass, writes only changed records (chatter stays meaningful).

        Only realized quantities count as covered: an issued but
        unfinished purchase order does not fulfil the need (BRD §4.5).
        """
        if not mip_by_move:
            return
        Mip = self.env["mip.need.line"].sudo()
        # one bulk read for every involved record — per-record attribute
        # access on singleton browses costs one query per MİP
        SYNC_FIELDS = ["need_date", "production_id", "current_qty",
                       "covered_qty", "remaining_qty", "state",
                       "doc_type", "doc_no"]
        rows = {d["id"]: d for d in Mip.browse(
            [e["id"] for e in mip_by_move.values()]).read(
            SYNC_FIELDS, load="_classic_write")}
        for mid, entry in mip_by_move.items():
            row = rows[entry["id"]]
            mv = ctx["moves"].get(mid)
            if not mv or mv["state"] == "cancel":
                vals = {"state": "cancel", "remaining_qty": 0.0}
            else:
                prod = ctx["prod"][mv["product_id"]]
                cur = self._conv(
                    ctx, mv["product_uom_qty"], mv["product_uom"],
                    prod["uom_id"])
                open_qty = self._conv(
                    ctx, self._open_qty(ctx, mv), mv["product_uom"],
                    prod["uom_id"])
                covered = max(0.0, cur - open_qty)
                if covered <= 0.0:
                    state = "open"
                elif covered >= cur:
                    state = "done"
                else:
                    state = "partial"
                vals = {
                    "need_date": self._local_date(
                        self._need_dt(mv), ctx),
                    "production_id": mv["raw_material_production_id"]
                        or False,
                    "current_qty": cur,
                    "covered_qty": covered,
                    "remaining_qty": open_qty,
                    "state": state,
                }
            diff = {k: v for k, v in vals.items() if row[k] != v}
            if (diff or not row["doc_no"]) and not entry.get("new"):
                # document labels change independently of quantities —
                # refresh them only when the record is actually touched;
                # records created seconds ago cannot have documents yet
                rec = Mip.browse(entry["id"])
                doc_type, doc_no = rec._doc_summary()
                if row["doc_type"] != doc_type:
                    diff["doc_type"] = doc_type
                if row["doc_no"] != doc_no:
                    diff["doc_no"] = doc_no
            if diff:
                # bulk bookkeeping writes skip chatter tracking — one
                # message per record would flood both mail and memory
                Mip.browse(entry["id"]).with_context(
                    tracking_disable=True).write(diff)

    # ------------------------------------------------------------------
    # BoM explosion — virtual (planned) component needs
    # ------------------------------------------------------------------

    @api.model
    def _get_bom_graph(self, need_products):
        """BoM structure for demanded products.

        Returns (bom_map, children, depth, component_products):
          bom_map   {tmpl_id: {qty, lines: [(product_id, qty)]}}
          depth     {tmpl_id: int} — level in the explosion tree so
                     parents are always processed before components
          comp_ids  product.product set — every component variant found
                    anywhere in the trees
        """
        Bom = self.env["mrp.bom"].sudo()
        manu_ids = self._get_manu_route_ids()
        bom_map, children = {}, {}
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
            if not boms:
                break
            # batch-read every BoM line found this level, then map the
            # component products to their templates in one read
            bl_rows = {
                d["id"]: d
                for d in self.env["mrp.bom.line"].sudo().browse(
                    boms.bom_line_ids.ids).read(
                    ["product_id", "product_qty"], load="_classic_write")}
            comp_pids = {d["product_id"] for d in bl_rows.values()
                         if d["product_id"]}
            comp_tmpl = {
                d["id"]: d["product_tmpl_id"]
                for d in self.env["product.product"].browse(
                    comp_pids).read(["product_tmpl_id"],
                                    load="_classic_write")}
            nxt = set()
            for d in boms.read(
                    ["product_tmpl_id", "product_qty", "bom_line_ids"],
                    load="_classic_write"):
                t = d["product_tmpl_id"]
                if t in bom_map:
                    continue
                lines = []
                for bl_id in d["bom_line_ids"]:
                    bl = bl_rows.get(bl_id)
                    if not bl or not bl["product_id"]:
                        continue
                    lines.append((bl["product_id"], bl["product_qty"]))
                    comp_ids.add(bl["product_id"])
                    ct = comp_tmpl.get(bl["product_id"])
                    if ct:
                        children.setdefault(t, set()).add(ct)
                        if ct not in seen:
                            seen.add(ct)
                            nxt.add(ct)
                bom_map[t] = {"qty": d["product_qty"] or 1.0,
                              "lines": lines}
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
    def _explode_bom(self, pid, walk, bom_map, manu_route_ids, ctx, out):
        """Turn the uncovered part of a manufactured product's needs
        into virtual component demands (dependent requirements).

        Only the shortage is exploded — quantities already covered by
        stock or incoming supply (including open MOs) produce no
        component need. The component is needed when production must
        start: need date minus the product's manufacturing lead time.
        """
        prod = ctx["prod"][pid]
        bom = bom_map.get(prod["tmpl_id"])
        if not bom or not (manu_route_ids & prod["routes"]):
            return
        delay_days = prod["produce_delay"] or 0
        detail = walk["detail"]
        for kind, entry in walk["needs"]:
            eid = entry["key"] if kind == "ev" else entry["id"]
            info = detail.get(eid)
            if not info or info["uncovered"] <= 0.0:
                continue
            if kind == "ev":
                need_date = entry["date"]
                wh_id = entry["warehouse_id"]
                company_id = entry["company_id"]
                location = entry["location"]
            else:
                need_date = self._local_date(self._need_dt(entry), ctx)
                wh_id = entry["warehouse_id"]
                company_id = entry["company_id"]
                location = ctx["loc_name"].get(entry["location_id"], "")
            prod_date = need_date - timedelta(days=delay_days)
            for comp_pid, comp_qty in bom["lines"]:
                qty = info["uncovered"] * comp_qty / bom["qty"]
                if qty <= 0.0:
                    continue
                key = "bom:%s:%s:%s" % (
                    comp_pid, wh_id or 0,
                    fields.Date.to_string(prod_date))
                ev = out[comp_pid].setdefault(key, {
                    "key": key,
                    "date": prod_date,
                    "qty": 0.0,
                    "parents": set(),
                    "company_id": company_id,
                    "warehouse_id": wh_id,
                    "location": location,
                })
                ev["qty"] += qty
                ev["parents"].add(prod["display_name"])

    @api.model
    def _ensure_virtual_mips(self, all_vevents, max_create=None):
        """Upsert MİP records for all virtual need rows in one batch —
        ({key: {id, name, rec}}, truncated). ``max_create`` bounds the
        batch the same way as _ensure_mip_lines."""
        if not all_vevents:
            return {}, False
        Mip = self.env["mip.need.line"].sudo()
        keys = [ev["key"] for ev in all_vevents]
        by_key = {}
        existing = Mip.search_read(
            [("key", "in", keys)], ["key", "name"],
            load="_classic_write")
        for d in existing:
            by_key[d["key"]] = {
                "id": d["id"], "name": d["name"],
                "rec": Mip.browse(d["id"]),
            }
        missing = [ev for ev in all_vevents if ev["key"] not in by_key]
        truncated = False
        if max_create is not None and len(missing) > max_create:
            missing = sorted(missing, key=lambda e: e["key"])[:max_create]
            truncated = True
        if missing:
            vals_list = [{
                "key": ev["key"],
                "product_id": int(ev["key"].split(":")[1]),
                "company_id": ev["company_id"],
                "warehouse_id": ev["warehouse_id"],
                "need_date": ev["date"],
                "source_type": "vp",
                "initial_qty": ev["qty"],
            } for ev in missing]
            # uom comes from the component product itself
            prod_uom = {
                d["id"]: d["uom_id"]
                for d in self.env["product.product"].browse(
                    {v["product_id"] for v in vals_list}).read(
                    ["uom_id"], load="_classic_write")}
            for v in vals_list:
                v["uom_id"] = prod_uom.get(v["product_id"])
            for i in range(0, len(vals_list), _MIP_CHUNK):
                created = Mip.create(vals_list[i:i + _MIP_CHUNK])
                for rec in created:
                    by_key[rec.key] = {
                        "id": rec.id, "name": rec.name, "rec": rec,
                        "new": True}
        return by_key, truncated

    @api.model
    def _sync_virtual_mips(self, vmips, virt_lines):
        """Write the computed quantities/state onto virtual MİP records
        (they have no stock move to derive them from) — diff-only."""
        if not vmips:
            return
        Mip = self.env["mip.need.line"].sudo()
        SYNC_FIELDS = ["need_date", "current_qty", "covered_qty",
                       "remaining_qty", "state", "doc_type", "doc_no"]
        rows = {d["id"]: d for d in Mip.browse(
            [i["id"] for i in vmips.values()]).read(
            SYNC_FIELDS, load="_classic_write")}
        for key, rec_info in vmips.items():
            ln = virt_lines.get(key)
            if not ln:
                continue
            row = rows[rec_info["id"]]
            covered = ln["covered_qty"]
            if ln["uncovered_qty"] <= 0.0:
                state = "done"
            elif covered > 0.0:
                state = "partial"
            else:
                state = "open"
            vals = {
                "need_date": fields.Date.to_date(ln["need_date"]),
                "current_qty": ln["need_qty"],
                "covered_qty": covered,
                "remaining_qty": ln["uncovered_qty"],
                "state": state,
            }
            diff = {k: v for k, v in vals.items() if row[k] != v}
            if (diff or not row["doc_no"]) and not rec_info.get("new"):
                rec = Mip.browse(rec_info["id"])
                doc_type, doc_no = rec._doc_summary()
                if row["doc_type"] != doc_type:
                    diff["doc_type"] = doc_type
                if row["doc_no"] != doc_no:
                    diff["doc_no"] = doc_no
            if diff:
                Mip.browse(rec_info["id"]).with_context(
                    tracking_disable=True).write(diff)

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
        self.env["mip.need.line"].sudo().search(domain).with_context(
            tracking_disable=True).write(
                {"state": "cancel", "remaining_qty": 0.0})

    @api.model
    def _get_virtual_requested(self, demand, vmips, ctx):
        """({key: requested qty}, {key: doc labels}, {key: pending docs})
        for virtual need keys linked through need_mip_ids."""
        if not vmips:
            return {}, {}, {}
        lines = self.env["purchase.request.line"].sudo().search([
            ("need_mip_ids", "in",
             [info["id"] for info in vmips.values()]),
            ("cancelled", "=", False),
            ("request_state", "in", list(ACTIVE_REQUEST_STATES)),
        ])
        mip_by_id = {info["id"]: info["rec"] for info in vmips.values()}
        mip_by_key = {k: info["rec"] for k, info in vmips.items()}
        alloc = defaultdict(float)
        docs = defaultdict(set)
        pend = defaultdict(list)
        for rl in lines:
            mips = [mip_by_id[i] for i in rl.need_mip_ids.ids
                    if i in mip_by_id]
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
                take = min(demand.get(mip.key, 0.0), remaining)
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

    # ------------------------------------------------------------------
    # data sources
    # ------------------------------------------------------------------

    @api.model
    def _get_reschedule_log(self, need_moves):
        """{move_id: [history dicts]} — the İstisna column's data."""
        rows = self.env["mip.reschedule.log"].sudo().search_read(
            [("move_id", "in", need_moves.ids)],
            ["move_id", "doc_name", "user_id", "change_date",
             "planned_date"],
            order="change_date, id")
        out = defaultdict(list)
        for d in rows:
            out[d["move_id"]].append({
                "doc": d["doc_name"] or "",
                "user": d["user_id"][1] if d["user_id"] else "",
                "date": fields.Datetime.to_string(d["change_date"]),
                "planned": fields.Date.to_string(d["planned_date"]),
            })
        return out

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
    def _get_requested_quantities(self, need_moves, ctx):
        """({move_id: requested qty}, {move_id: doc-type labels},
            {move_id: [pending doc entries]}).

        A merged request line is attributed to its need moves in
        need-date order — earliest needs are considered served first,
        matching the merge order — so a partially requested need line
        keeps its remaining quantity requestable (BRD §7.2)."""
        # sudo: dedup must work even for users who cannot read purchase
        # request lines directly (BRD §10)
        lines = self.env["purchase.request.line"].sudo().search([
            ("need_move_ids", "in", need_moves.ids),
            ("cancelled", "=", False),
            ("request_state", "in", list(ACTIVE_REQUEST_STATES)),
        ])
        move_data = ctx["moves"]
        alloc = defaultdict(float)
        docs = defaultdict(set)
        pend = defaultdict(list)
        for rl in lines:
            mids = [i for i in rl.need_move_ids.ids if i in move_data]
            mids.sort(key=lambda i: (
                move_data[i]["date"] or fields.Datetime.now(), i))
            labels = self._request_doc_labels(rl)
            for mid in mids:
                docs[mid] |= labels
            remaining = rl.product_uom_id._compute_quantity(
                rl.product_qty, rl.product_id.uom_id, round=False)
            takes = []
            last = None
            for mid in mids:
                if remaining <= 0.0:
                    break
                mv = move_data[mid]
                open_need = self._conv(
                    ctx, self._open_qty(ctx, mv), mv["product_uom"],
                    ctx["prod"][mv["product_id"]]["uom_id"])
                take = min(open_need, remaining)
                takes.append((mid, take))
                alloc[mid] += take
                remaining -= take
                last = mid
            if remaining > 0.0 and last is not None:
                # planner asked for more than the raw need — attribute
                # the surplus to the latest need so sums stay truthful
                alloc[last] += remaining
                mid, take = takes[-1]
                takes[-1] = (mid, take + remaining)
            req_label = self.env._("Onaysız Talep") \
                if rl.request_state in ("draft", "to_approve") \
                else self.env._("Onaylı Talep")
            for mid, take in takes:
                if take > 0.0:
                    pend[mid].append({
                        "type": req_label,
                        "doc": rl.request_id.name,
                        "model": "purchase.request",
                        "res_id": rl.request_id.id,
                        "qty": take,
                        "uom": ctx["prod"][
                            move_data[mid]["product_id"]]["uom_name"],
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
                last_mid = None
                for mid, take in takes:
                    if left <= 0.0:
                        break
                    share = min(take, left)
                    if share <= 0.0:
                        continue
                    pend[mid].append({
                        "type": po_label,
                        "doc": order.name,
                        "model": "purchase.order",
                        "res_id": order.id,
                        "qty": share,
                        "uom": ctx["prod"][
                            move_data[mid]["product_id"]]["uom_name"],
                        "date": po_date,
                    })
                    left -= share
                    last_mid = mid
                if left > 0.0 and last_mid is not None:
                    pend[last_mid][-1]["qty"] += left
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
    def _get_lead_info(self, products, ctx):
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
        for pid in products.ids:
            proc = ctx["prod"][pid]["proc_days"]
            if proc:
                info[pid] = {"proc": proc, "missing": False}
            elif default_set:
                info[pid] = {"proc": default_days, "missing": False}
            else:
                info[pid] = {"proc": 0, "missing": True}
        return info



