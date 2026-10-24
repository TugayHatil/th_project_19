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
            query: "",
            uncoveredOnly: false,
            lateOnly: false,
            showSource: false,
            showMip: false,
            showType: false,
            showExc: false,
            showRoute: false,
            colsOpen: false,
            // unified search bar: one input, option menu underneath —
            // "Ürün" applies the text filter, "Odak" picks a BoM product
            searchText: "",
            searchOpen: false,
            focusResults: [],
            focusProductId: false,
            focusProductName: "",
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

    get totalPages() {
        return Math.max(
            1, Math.ceil(this.state.total / this.state.pageSize));
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
                    query: this.state.query || "",
                    limit: this.state.pageSize,
                    offset: this.state.page * this.state.pageSize,
                    uncovered_only: this.state.uncoveredOnly,
                    late_only: this.state.lateOnly,
                    sort_by: this.state.sortBy,
                    focus_product_id: this.state.focusProductId || false,
                });
            this.state.groups = data.groups || [];
            this.state.total = data.total || 0;
            this.state.today = data.today || this.state.today;
            // warehouse/date/query change the computed plan itself —
            // prune every cached detail and selection only then; mere
            // paging/filtering keeps them so selections survive pages
            const fkey = [
                this.state.warehouseId, this.state.dateFrom,
                this.state.dateTo, this.state.query,
                this.state.focusProductId].join("|");
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

    onSearchbarInput(ev) {
        const text = ev.target.value;
        this.state.searchText = text;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(async () => {
            if (!text.trim()) {
                this.state.searchOpen = false;
                this.state.focusResults = [];
                return;
            }
            try {
                this.state.focusResults = await this.orm.call(
                    "mrp.purchase.need", "search_focus_products",
                    [text]);
                this.state.searchOpen = true;
            } catch (error) {
                this.notifyError(error, _t("Ürün araması yapılamadı."));
            }
        }, SEARCH_DELAY);
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.applyProductSearch();
        } else if (ev.key === "Escape") {
            this.closeSearchMenu();
        }
    }

    async applyProductSearch() {
        this.state.query = this.state.searchText.trim();
        this.state.searchText = "";
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async clearQuery() {
        this.state.query = "";
        this.state.searchText = "";
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async selectFocus(product) {
        this.state.focusProductId = product.id;
        this.state.focusProductName = product.name;
        this.state.searchText = "";
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async clearFocus() {
        this.state.focusProductId = false;
        this.state.focusProductName = "";
        this.state.focusResults = [];
        this.state.searchOpen = false;
        this.state.page = 0;
        await this.loadGroups();
    }

    closeSearchMenu() {
        this.state.searchOpen = false;
    }

    async onWarehouseChange(ev) {
        this.state.warehouseId = ev.target.value ? parseInt(ev.target.value, 10) : false;
        this.state.page = 0;
        await this.loadGroups();
    }

    async onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        this.state.page = 0;
        await this.loadGroups();
    }

    async onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        this.state.page = 0;
        await this.loadGroups();
    }

    onUncoveredChange(ev) {
        this.state.uncoveredOnly = ev.target.checked;
        this.state.page = 0;
        this.loadGroups();
    }

    onLateChange(ev) {
        this.state.lateOnly = ev.target.checked;
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
