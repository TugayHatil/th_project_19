/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { Dialog } from "@web/core/dialog/dialog";

const SEARCH_DELAY = 350;

export class SuggestionsDialog extends Component {
    static template = "mrp_purchase_need_plan.SuggestionsDialog";
    static components = { Dialog };
    static props = {
        suggestions: Array,
        openOrder: Function,
        fmtDate: Function,
        fmtQty: Function,
        close: Function,
    };

    onOrderClick(sug) {
        this.props.close();
        this.props.openOrder(sug);
    }
}

export class CoverageDialog extends Component {
    static template = "mrp_purchase_need_plan.CoverageDialog";
    static components = { Dialog };
    static props = {
        coverage: Array,
        openOrder: Function,
        fmtDate: Function,
        fmtQty: Function,
        close: Function,
    };

    onOrderClick(item) {
        this.props.close();
        this.props.openOrder(item);
    }
}

export class RescheduleDialog extends Component {
    static template = "mrp_purchase_need_plan.RescheduleDialog";
    static components = { Dialog };
    static props = {
        logs: Array,
        fmtDate: Function,
        close: Function,
    };
}

export class NeedPlan extends Component {
    static template = "mrp_purchase_need_plan.NeedPlan";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            loading: false,
            creating: false,
            groups: [],
            // product_id -> need line list, filled lazily on expand (BRD §9)
            lines: {},
            suggestions: {},
            expanded: {},
            selected: {},
            // need key -> planner-edited request quantity
            requestQty: {},
            warehouses: [],
            warehouseId: false,
            dateFrom: "",
            dateTo: "",
            // need-date period preset — "" = Tümü
            period: "",
            periodOpen: false,
            // applied product-search terms — each Enter adds a facet,
            // facets OR together, Backspace on empty input pops the last
            queries: [],
            uncoveredOnly: false,
            showCovered: false,
            showSource: false,
            showMip: false,
            showType: false,
            showExc: false,
            showRoute: false,
            showMipResp: false,
            showSaResp: false,
            colsOpen: false,
            // unified search bar: one input, option menu underneath —
            // "Ürün" applies the text filter, "Odak" picks a BoM product
            searchText: "",
            searchOpen: false,
            activeIndex: 0,
            prodExpanded: false,
            prodResults: [],
            focusExpanded: false,
            focusResults: [],
            mipExpanded: false,
            saExpanded: false,
            whExpanded: false,
            userResults: [],
            // focus facets — one per BoM product; scopes union
            focusProducts: [],
            mipRespId: false,
            mipRespName: "",
            saRespId: false,
            saRespName: "",
            sortBy: "purchase_start",
            canCreate: false,
            today: "",
            // server-side paging — the group list itself is paged so the
            // DOM never holds more than a page of rows at scale (BRD §9)
            page: 0,
            pageSize: 50,
            total: 0,
        });
        this._searchTimer = null;
        // warehouse/date/query change the underlying plan; page & view
        // filters don't — selections survive paging but not refiltering
        this._filterKey = null;
        // need key -> product_id, so a line selection can be pruned when
        // its group disappears or reloads
        this._selOwner = {};
        onMounted(async () => {
            await this.loadFilters();
            await this.loadGroups();
        });
    }

    // -- derived data -----------------------------------------------------

    get visibleGroups() {
        // filtering + sorting + paging all happen server-side already
        return this.state.groups;
    }

    get selectedCount() {
        return Object.values(this.state.selected).filter(Boolean).length;
    }

    isSelectable(line) {
        return line.requestable_qty > 0 && line.can_buy !== false;
    }

    get missingConfigGroups() {
        return this.state.groups.filter((g) => g.missing_lead_config);
    }

    // -- data -------------------------------------------------------------

    notifyError(error, fallback) {
        this.notification.add(
            error.data?.message || error.message || fallback,
            { type: "danger" },
        );
    }

    async loadFilters() {
        try {
            const data = await this.orm.call(
                "mrp.purchase.need", "get_filters", []);
            this.state.warehouses = data.warehouses || [];
            this.state.canCreate = data.can_create_request;
            this.state.today = data.today;
        } catch (error) {
            this.notifyError(error, _t("Filtreler yüklenemedi."));
        }
    }

    async loadGroups(force) {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "mrp.purchase.need", "get_need_groups", [], {
                    force: Boolean(force),
                    warehouse_id: this.state.warehouseId || false,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                    query: this.state.queries.length
                        ? this.state.queries : "",
                    limit: this.state.pageSize,
                    offset: this.state.page * this.state.pageSize,
                    uncovered_only: this.state.uncoveredOnly,
                    show_covered: this.state.showCovered,
                    sort_by: this.state.sortBy,
                    focus_product_id: this.state.focusProducts.length
                        ? this.state.focusProducts.map((p) => p.id)
                        : false,
                    mip_resp_id: this.state.mipRespId || false,
                    sa_resp_id: this.state.saRespId || false,
                });
            this.state.groups = data.groups || [];
            this.state.total = data.total || 0;
            this.state.today = data.today || this.state.today;
            // warehouse/date/query change the computed plan itself —
            // prune every cached detail and selection only then; mere
            // paging/filtering keeps them so selections survive pages
            const fkey = [
                this.state.warehouseId, this.state.dateFrom,
                this.state.dateTo, this.state.queries.join(","),
                this.state.focusProducts.map((p) => p.id).join(","),
                this.state.mipRespId, this.state.saRespId,
                this.state.uncoveredOnly, this.state.showCovered].join("|");
            if (this._filterKey !== fkey) {
                this._filterKey = fkey;
                this.state.lines = {};
                this.state.suggestions = {};
                this.state.expanded = {};
                this.state.selected = {};
                this._selOwner = {};
                this.state.requestQty = {};
            }
            // refetch detail of groups still expanded on this page so
            // they never render stale lines
            const reloads = [];
            const visible = new Set(
                this.state.groups.map((g) => g.product_id));
            for (const pid of Object.keys(this.state.expanded)) {
                if (!this.state.expanded[pid]) {
                    continue;
                }
                const group = this.state.groups.find(
                    (g) => g.product_id === parseInt(pid, 10));
                if (group && visible.has(group.product_id)) {
                    reloads.push(this.loadLines(group));
                }
            }
            await Promise.all(reloads);
        } catch (error) {
            this.notifyError(error, _t("Planlama verisi yüklenemedi."));
        } finally {
            this.state.loading = false;
        }
    }

    async loadLines(group) {
        const pid = group.product_id;
        // mark as loading so stale detail never renders while refetching
        delete this.state.lines[pid];
        try {
            const data = await this.orm.call(
                "mrp.purchase.need", "get_need_lines", [], {
                    product_id: pid,
                    warehouse_id: this.state.warehouseId || false,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                    include_covered: this.state.showCovered
                        || this.state.focusProducts.length > 0,
                    uncovered_only: this.state.uncoveredOnly,
                });
            this.state.lines[pid] = data.lines || [];
            this.state.suggestions[pid] = data.suggestions || [];
            // drop selections that no longer point at a visible line
            const ids = new Set(this.state.lines[pid].map((l) => l.key));
            for (const key of Object.keys(this.state.selected)) {
                if (!ids.has(key) && this._selOwner[key] === pid) {
                    delete this.state.selected[key];
                    delete this._selOwner[key];
                    delete this.state.requestQty[key];
                }
            }
            if (data.group) {
                // keep the header in sync with the lazily computed detail
                Object.assign(group, data.group);
            }
        } catch (error) {
            this.state.expanded[pid] = false;
            this.notifyError(error, _t("İhtiyaç detayları yüklenemedi."));
        }
    }

    async toggleGroup(group) {
        const pid = group.product_id;
        if (this.state.expanded[pid]) {
            this.state.expanded[pid] = false;
            return;
        }
        this.state.expanded[pid] = true;
        if (!this.state.lines[pid]) {
            await this.loadLines(group);
        }
    }

    toggleLine(line, group, ev) {
        const mid = line.key;
        if (ev.target.checked) {
            this.state.selected[mid] = true;
            this._selOwner[mid] = group.product_id;
        } else {
            delete this.state.selected[mid];
            delete this._selOwner[mid];
            delete this.state.requestQty[mid];
        }
    }

    async toggleSelectAll(group, ev) {
        const want = ev.target.checked;
        if (want && !this.state.lines[group.product_id]) {
            // need the rows to know which lines exist — load & expand
            this.state.expanded[group.product_id] = true;
            await this.loadLines(group);
        }
        for (const line of this.state.lines[group.product_id] || []) {
            if (!this.isSelectable(line)) {
                continue;
            }
            if (want) {
                this.state.selected[line.key] = true;
                this._selOwner[line.key] = group.product_id;
            } else {
                delete this.state.selected[line.key];
                delete this._selOwner[line.key];
                delete this.state.requestQty[line.key];
            }
        }
    }

    groupChecked(group) {
        const lines = this.state.lines[group.product_id] || [];
        const eligible = lines.filter((l) => this.isSelectable(l));
        return eligible.length > 0
            && eligible.every((l) => this.state.selected[l.key]);
    }

    requestQtyOf(line) {
        const v = this.state.requestQty[line.key];
        return v === undefined ? "" : v;
    }

    effectiveQtyOf(line) {
        // empty "Planla" input means "request the full remaining qty"
        const v = this.state.requestQty[line.key];
        return v === undefined
            ? (line.requestable_qty || line.uncovered_qty || 0)
            : v;
    }

    onQtyChange(line, ev) {
        if (ev.target.value === "") {
            delete this.state.requestQty[line.key];
            return;
        }
        const v = parseFloat(ev.target.value);
        this.state.requestQty[line.key] = Number.isNaN(v) ? 0 : v;
    }

    groupSelectedQty(group) {
        let total = 0;
        for (const line of this.state.lines[group.product_id] || []) {
            if (this.state.selected[line.key]) {
                total += this.effectiveQtyOf(line);
            }
        }
        return total;
    }

    async onCreateRequest() {
        const lineKeys = Object.keys(this.state.selected)
            .filter((k) => this.state.selected[k]);
        if (!lineKeys.length) {
            return;
        }
        const moveQuantities = {};
        for (const key of lineKeys) {
            const q = this.state.requestQty[key];
            if (q !== undefined) {
                moveQuantities[key] = q;
            }
        }
        this.state.creating = true;
        try {
            const res = await this.orm.call(
                "mrp.purchase.need", "create_purchase_request", [], {
                    line_keys: lineKeys,
                    move_quantities: moveQuantities,
                    warehouse_id: this.state.warehouseId || false,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                });
            const names = (res.requests || []).map((r) => r.name).join(", ");
            let msg = names
                ? `${_t("Satınalma talebi oluşturuldu:")} ${names}`
                : _t("Satınalma talebi oluşturuldu.");
            if (res.skipped && res.skipped.length) {
                msg += ` — ${_t("zaten karşılanıyor:")} ${res.skipped.join(", ")}`;
            }
            this.notification.add(msg, { type: "success" });
            this.state.selected = {};
            await this.loadGroups();
            if (res.requests && res.requests.length === 1) {
                await this.action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "purchase.request",
                    res_id: res.requests[0].id,
                    views: [[false, "form"]],
                });
            } else if (res.requests && res.requests.length > 1) {
                await this.action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "purchase.request",
                    domain: [["id", "in", res.requests.map((r) => r.id)]],
                    views: [[false, "list"], [false, "form"]],
                });
            }
        } catch (error) {
            this.notifyError(error, _t("Satınalma talebi oluşturulamadı."));
        } finally {
            this.state.creating = false;
        }
    }

    // -- toolbar handlers -------------------------------------------------

    // -- unified search bar -------------------------------------------------

    get searchItems() {
        // flattened menu rows so keyboard navigation works across the
        // headers and their expandable suggestion lists — the Odoo
        // search-view pattern
        const items = [{ type: "product" }];
        if (this.state.prodExpanded) {
            if (this.state.prodResults.length) {
                for (const p of this.state.prodResults) {
                    items.push({ type: "prod", prod: p });
                }
            } else {
                items.push({ type: "empty" });
            }
        }
        items.push({ type: "focusHeader" });
        if (this.state.focusExpanded) {
            if (this.state.focusResults.length) {
                for (const p of this.state.focusResults) {
                    items.push({ type: "focus", prod: p });
                }
            } else {
                items.push({ type: "empty" });
            }
        }
        items.push({ type: "mipHeader" });
        if (this.state.mipExpanded) {
            if (this.state.userResults.length) {
                for (const u of this.state.userResults) {
                    items.push({ type: "mip", user: u });
                }
            } else {
                items.push({ type: "empty" });
            }
        }
        items.push({ type: "saHeader" });
        if (this.state.saExpanded) {
            if (this.state.userResults.length) {
                for (const u of this.state.userResults) {
                    items.push({ type: "sa", user: u });
                }
            } else {
                items.push({ type: "empty" });
            }
        }
        items.push({ type: "whHeader" });
        if (this.state.whExpanded) {
            const whs = this.whResults;
            if (whs.length) {
                for (const w of whs) {
                    items.push({ type: "wh", wh: w });
                }
            } else {
                items.push({ type: "empty" });
            }
        }
        return items;
    }

    get whResults() {
        // warehouses are already loaded for the toolbar — filter the
        // small list client-side instead of an extra RPC
        const q = this.state.searchText.trim().toLowerCase();
        const list = this.state.warehouses || [];
        if (!q) {
            return list;
        }
        return list.filter(
            (w) => (w.name || "").toLowerCase().includes(q)
                || (w.code || "").toLowerCase().includes(q));
    }

    get warehouseName() {
        const wh = (this.state.warehouses || []).find(
            (w) => w.id === this.state.warehouseId);
        return wh ? `${wh.name} (${wh.code})` : "";
    }

    onSearchbarInput(ev) {
        const text = ev.target.value;
        this.state.searchText = text;
        this.state.searchOpen = Boolean(text.trim());
        this.state.activeIndex = 0;
        this.state.prodExpanded = false;
        this.state.focusExpanded = false;
        this.state.mipExpanded = false;
        this.state.saExpanded = false;
        this.state.whExpanded = false;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(async () => {
            if (!text.trim()) {
                this.state.prodResults = [];
                this.state.focusResults = [];
                return;
            }
            try {
                const [prods, focus, users] = await Promise.all([
                    this.orm.call(
                        "mrp.purchase.need", "search_products", [text]),
                    this.orm.call(
                        "mrp.purchase.need", "search_focus_products",
                        [text]),
                    this.orm.call(
                        "mrp.purchase.need", "search_users", [text]),
                ]);
                this.state.prodResults = prods;
                this.state.focusResults = focus;
                this.state.userResults = users;
            } catch (error) {
                this.notifyError(error, _t("Ürün araması yapılamadı."));
            }
        }, SEARCH_DELAY);
    }

    toggleFocusGroup() {
        this.state.focusExpanded = !this.state.focusExpanded;
    }

    toggleProdGroup() {
        this.state.prodExpanded = !this.state.prodExpanded;
    }

    toggleMipGroup() {
        this.state.mipExpanded = !this.state.mipExpanded;
    }

    toggleSaGroup() {
        this.state.saExpanded = !this.state.saExpanded;
    }

    toggleWhGroup() {
        this.state.whExpanded = !this.state.whExpanded;
    }

    onSearchKeydown(ev) {
        const items = this.searchItems;
        const item = items[this.state.activeIndex];
        if (ev.key === "ArrowDown") {
            ev.preventDefault();
            this.state.activeIndex = Math.min(
                this.state.activeIndex + 1, items.length - 1);
        } else if (ev.key === "ArrowUp") {
            ev.preventDefault();
            this.state.activeIndex = Math.max(this.state.activeIndex - 1, 0);
        } else if (ev.key === "ArrowRight") {
            this.expandItem(item, true);
        } else if (ev.key === "ArrowLeft") {
            this.expandItem(item, false);
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            this.activateSearchItem();
        } else if (ev.key === "Escape") {
            this.closeSearchMenu();
        } else if (ev.key === "Backspace" && !ev.target.value) {
            // empty input + Backspace pops the last facet — the Odoo
            // search-view convention
            if (this.state.warehouseId) {
                this.clearWarehouse();
            } else if (this.state.saRespId) {
                this.clearSaResp();
            } else if (this.state.mipRespId) {
                this.clearMipResp();
            } else if (this.state.focusProducts.length) {
                this.clearFocus(this.state.focusProducts.length - 1);
            } else if (this.state.queries.length) {
                this.state.queries.pop();
                this.state.page = 0;
                this.loadGroups();
            }
        }
    }

    expandItem(item, open) {
        const flag = {
            product: "prodExpanded",
            focusHeader: "focusExpanded",
            mipHeader: "mipExpanded",
            saHeader: "saExpanded",
            whHeader: "whExpanded",
        }[item.type];
        if (flag) {
            this.state[flag] = open;
        }
    }

    activateSearchItem() {
        const it = this.searchItems[this.state.activeIndex];
        if (!it) {
            return;
        }
        // Enter on a header expands it — the matching records are
        // listed underneath; Enter never collapses (use ← or the caret)
        if (it.type === "product") {
            return this.applyProductSearch();
        }
        if (it.type === "prod") {
            return this.applyProductSearch(it.prod.term);
        }
        if (it.type === "focusHeader") {
            // Enter applies the search: every BoM product matching the
            // term becomes a focus facet — the → arrow is for browsing
            return this.applyFocusSearch();
        }
        if (it.type === "mipHeader") {
            this.state.mipExpanded = true;
            return;
        }
        if (it.type === "saHeader") {
            this.state.saExpanded = true;
            return;
        }
        if (it.type === "whHeader") {
            this.state.whExpanded = true;
            return;
        }
        this.activateItem(it);
    }

    activateItem(it) {
        if (it.type === "prod") {
            return this.applyProductSearch(it.prod.term);
        }
        if (it.type === "focusHeader") {
            return this.toggleFocusGroup();
        }
        if (it.type === "mipHeader") {
            return this.toggleMipGroup();
        }
        if (it.type === "saHeader") {
            return this.toggleSaGroup();
        }
        if (it.type === "whHeader") {
            return this.toggleWhGroup();
        }
        if (it.type === "focus") {
            return this.selectFocus(it.prod);
        }
        if (it.type === "mip") {
            return this.selectMipResp(it.user);
        }
        if (it.type === "sa") {
            return this.selectSaResp(it.user);
        }
        if (it.type === "wh") {
            return this.selectWarehouse(it.wh);
        }
        if (it.type === "product") {
            return this.applyProductSearch();
        }
    }

    async applyProductSearch(term) {
        const t = (term || this.state.searchText).trim();
        this.state.searchText = "";
        this.state.searchOpen = false;
        if (t && !this.state.queries.includes(t)) {
            this.state.queries.push(t);
        }
        this.state.page = 0;
        await this.loadGroups();
    }

    async removeQuery(index) {
        this.state.queries.splice(index, 1);
        this.state.page = 0;
        await this.loadGroups();
    }

    async selectFocus(product) {
        if (!this.state.focusProducts.some((p) => p.id === product.id)) {
            this.state.focusProducts.push(
                { id: product.id, name: product.name });
        }
        this.state.searchText = "";
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async applyFocusSearch() {
        for (const p of this.state.focusResults) {
            if (!this.state.focusProducts.some((f) => f.id === p.id)) {
                this.state.focusProducts.push({ id: p.id, name: p.name });
            }
        }
        this.state.searchText = "";
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async clearFocus(index) {
        this.state.focusProducts.splice(index, 1);
        this.state.page = 0;
        await this.loadGroups();
    }

    async selectMipResp(user) {
        this.state.mipRespId = user.id;
        this.state.mipRespName = user.name;
        this.state.searchText = "";
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async clearMipResp() {
        this.state.mipRespId = false;
        this.state.mipRespName = "";
        this.state.page = 0;
        await this.loadGroups();
    }

    async selectSaResp(user) {
        this.state.saRespId = user.id;
        this.state.saRespName = user.name;
        this.state.searchText = "";
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async clearSaResp() {
        this.state.saRespId = false;
        this.state.saRespName = "";
        this.state.page = 0;
        await this.loadGroups();
    }

    async selectWarehouse(wh) {
        this.state.warehouseId = wh.id;
        this.state.searchText = "";
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async clearWarehouse() {
        this.state.warehouseId = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    closeSearchMenu() {
        this.state.searchOpen = false;
    }

    // -- need-date period presets -------------------------------------------

    get periodLabel() {
        return {
            late: "Geciken",
            today: "Bugün",
            week: "Bu Hafta",
            month: "Bu Ay",
            year: "Bu Yıl",
        }[this.state.period] || "";
    }

    togglePeriodMenu() {
        this.state.periodOpen = !this.state.periodOpen;
    }

    _iso(d) {
        return d.toISOString().slice(0, 10);
    }

    async setPeriod(period) {
        // date bounds are computed from the server "today" the toolbar
        // already carries, so no clock/locale drift affects the ranges
        const base = this.state.today
            ? new Date(`${this.state.today}T12:00:00`)
            : new Date();
        let from = "";
        let to = "";
        if (period === "late") {
            to = this._iso(new Date(
                base.getFullYear(), base.getMonth(), base.getDate() - 1));
        } else if (period === "today") {
            from = to = this._iso(base);
        } else if (period === "week") {
            const dow = (base.getDay() + 6) % 7;   // Monday = 0
            const mon = new Date(
                base.getFullYear(), base.getMonth(),
                base.getDate() - dow);
            const sun = new Date(
                base.getFullYear(), base.getMonth(),
                base.getDate() - dow + 6);
            from = this._iso(mon);
            to = this._iso(sun);
        } else if (period === "month") {
            from = this._iso(new Date(
                base.getFullYear(), base.getMonth(), 1));
            to = this._iso(new Date(
                base.getFullYear(), base.getMonth() + 1, 0));
        } else if (period === "year") {
            from = this._iso(new Date(base.getFullYear(), 0, 1));
            to = this._iso(new Date(base.getFullYear(), 11, 31));
        }
        this.state.period = period;
        this.state.dateFrom = from;
        this.state.dateTo = to;
        this.state.periodOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    onUncoveredChange(ev) {
        this.state.uncoveredOnly = ev.target.checked;
        if (ev.target.checked) {
            this.state.showCovered = false;
        }
        this.state.page = 0;
        this.loadGroups();
    }

    onShowCoveredChange(ev) {
        this.state.showCovered = ev.target.checked;
        if (ev.target.checked) {
            this.state.uncoveredOnly = false;
        }
        this.state.page = 0;
        this.loadGroups();
    }

    onSourceToggle(ev) {
        this.state.showSource = ev.target.checked;
    }

    onMipToggle(ev) {
        this.state.showMip = ev.target.checked;
    }

    onTypeToggle(ev) {
        this.state.showType = ev.target.checked;
    }

    onExcToggle(ev) {
        this.state.showExc = ev.target.checked;
    }

    onRouteToggle(ev) {
        this.state.showRoute = ev.target.checked;
    }

    onMipRespToggle(ev) {
        this.state.showMipResp = ev.target.checked;
    }

    onSaRespToggle(ev) {
        this.state.showSaResp = ev.target.checked;
    }

    toggleColsMenu() {
        this.state.colsOpen = !this.state.colsOpen;
    }

    onSortChange(ev) {
        this.state.sortBy = ev.target.value;
        this.state.page = 0;
        this.loadGroups();
    }

    prevPage() {
        if (this.state.page > 0) {
            this.state.page -= 1;
            this.loadGroups();
        }
    }

    nextPage() {
        if ((this.state.page + 1) * this.state.pageSize < this.state.total) {
            this.state.page += 1;
            this.loadGroups();
        }
    }

    // -- rendering helpers ------------------------------------------------

    fmtQty(value) {
        return formatFloat(value || 0, { digits: [16, 2] });
    }

    daysUntil(value) {
        if (!value || !this.state.today) {
            return "";
        }
        const diff = new Date(value) - new Date(this.state.today);
        return Math.round(diff / 86400000);
    }

    fmtDate(value) {
        if (!value) {
            return "";
        }
        // fixed dd.mm.yyyy, parsed from the ISO string so timezone
        // offsets never shift the displayed day
        const [y, m, d] = String(value).slice(0, 10).split("-");
        return `${d}.${m}.${y}`;
    }

    isExpanded(group) {
        return !!this.state.expanded[group.product_id];
    }

    isLineSelected(line) {
        return !!this.state.selected[line.key];
    }

    groupLines(group) {
        return this.state.lines[group.product_id] || [];
    }

    groupSuggestions(group) {
        return this.state.suggestions[group.product_id] || [];
    }

    async openSuggestions(group) {
        if (this.state.suggestions[group.product_id] === undefined) {
            await this.loadLines(group);
        }
        this.dialog.add(SuggestionsDialog, {
            suggestions: this.groupSuggestions(group),
            openOrder: (sug) => this.openOrder(sug),
            fmtDate: (d) => this.fmtDate(d),
            fmtQty: (q) => this.fmtQty(q),
        });
    }

    openCoverage(line) {
        this.dialog.add(CoverageDialog, {
            coverage: line.coverage || [],
            openOrder: (item) => this.openOrder({ order_id: item.order_id }),
            fmtDate: (d) => this.fmtDate(d),
            fmtQty: (q) => this.fmtQty(q),
        });
    }

    async openLineDoc(line) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: line.doc_model,
            res_id: line.doc_id,
            views: [[false, "form"]],
        });
    }

    openExceptions(line) {
        this.dialog.add(RescheduleDialog, {
            logs: line.exception_log || [],
            fmtDate: (d) => this.fmtDate(d),
        });
    }

    async openOrder(suggestion) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: suggestion.order_id,
            views: [[false, "form"]],
        });
    }

    groupClass(group) {
        let cls = "o_mnp_group";
        if (group.has_late) {
            cls += " o_mnp_late";
        }
        if (group.total_uncovered <= 0) {
            cls += " o_mnp_covered";
        }
        return cls;
    }

    lineClass(line) {
        let cls = "o_mnp_line";
        if (line.uncovered_qty <= 0) {
            cls += " o_mnp_covered";
        }
        return cls;
    }
}

registry.category("actions").add("mrp_purchase_need_plan.screen", NeedPlan);
