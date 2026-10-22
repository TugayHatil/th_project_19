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
            // move_id -> planner-edited request quantity
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
            colsOpen: false,
            sortBy: "purchase_start",
            canCreate: false,
            today: "",
        });
        this._searchTimer = null;
        // move_id -> product_id, so a line selection can be pruned when
        // its group disappears or reloads
        this._selOwner = {};
        onMounted(async () => {
            await this.loadFilters();
            await this.loadGroups();
        });
    }

    // -- derived data -----------------------------------------------------

    get visibleGroups() {
        let groups = this.state.groups;
        if (this.state.uncoveredOnly) {
            groups = groups.filter((g) => g.total_uncovered > 0);
        }
        if (this.state.lateOnly) {
            groups = groups.filter((g) => g.has_late);
        }
        const key = this.state.sortBy === "need_date"
            ? "earliest_need"
            : "earliest_start";
        return [...groups].sort(
            (a, b) => (a[key] < b[key] ? -1 : a[key] > b[key] ? 1 : 0));
    }

    get selectedCount() {
        return Object.values(this.state.selected).filter(Boolean).length;
    }

    isSelectable(line) {
        return line.requestable_qty > 0;
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

    async loadGroups() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "mrp.purchase.need", "get_need_groups", [], {
                    warehouse_id: this.state.warehouseId || false,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                    query: this.state.query || "",
                });
            this.state.groups = data.groups || [];
            this.state.today = data.today || this.state.today;
            // server may have dropped products -> prune cached detail
            const alive = new Set(this.state.groups.map((g) => g.product_id));
            for (const pid of Object.keys(this.state.lines)) {
                if (!alive.has(parseInt(pid, 10))) {
                    delete this.state.lines[pid];
                    delete this.state.suggestions[pid];
                    delete this.state.expanded[pid];
                }
            }
            for (const [moveId, ownerPid] of Object.entries(this._selOwner)) {
                if (!alive.has(ownerPid)) {
                    delete this.state.selected[moveId];
                    delete this._selOwner[moveId];
                    delete this.state.requestQty[moveId];
                }
            }
            // filters may have changed -> refetch detail of groups that
            // are still expanded so they never render stale lines
            const reloads = [];
            for (const pid of Object.keys(this.state.expanded)) {
                if (!this.state.expanded[pid]) {
                    continue;
                }
                const group = this.state.groups.find(
                    (g) => g.product_id === parseInt(pid, 10));
                if (group) {
                    reloads.push(this.loadLines(group));
                } else {
                    delete this.state.expanded[pid];
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
            // default the editable request qty to the uncovered qty
            for (const line of this.state.lines[pid]) {
                if (this.isSelectable(line)
                        && this.state.requestQty[line.move_id] === undefined) {
                    this.state.requestQty[line.move_id] = line.requestable_qty;
                }
            }
            // drop selections that no longer point at a visible line
            const ids = new Set(this.state.lines[pid].map((l) => l.move_id));
            for (const moveId of Object.keys(this.state.selected)) {
                if (!ids.has(parseInt(moveId, 10)) && this._selOwner[moveId] === pid) {
                    delete this.state.selected[moveId];
                    delete this._selOwner[moveId];
                    delete this.state.requestQty[moveId];
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
        const mid = line.move_id;
        if (ev.target.checked) {
            this.state.selected[mid] = true;
            this._selOwner[mid] = group.product_id;
            if (this.state.requestQty[mid] === undefined) {
                this.state.requestQty[mid] = line.requestable_qty;
            }
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
                this.state.selected[line.move_id] = true;
                this._selOwner[line.move_id] = group.product_id;
                if (this.state.requestQty[line.move_id] === undefined) {
                    this.state.requestQty[line.move_id] = line.requestable_qty;
                }
            } else {
                delete this.state.selected[line.move_id];
                delete this._selOwner[line.move_id];
                delete this.state.requestQty[line.move_id];
            }
        }
    }

    groupChecked(group) {
        const lines = this.state.lines[group.product_id] || [];
        const eligible = lines.filter((l) => this.isSelectable(l));
        return eligible.length > 0
            && eligible.every((l) => this.state.selected[l.move_id]);
    }

    requestQtyOf(line) {
        const v = this.state.requestQty[line.move_id];
        return v === undefined ? line.requestable_qty : v;
    }

    onQtyChange(line, ev) {
        const v = parseFloat(ev.target.value);
        this.state.requestQty[line.move_id] = Number.isNaN(v) ? 0 : v;
    }

    groupSelectedQty(group) {
        let total = 0;
        for (const line of this.state.lines[group.product_id] || []) {
            if (this.state.selected[line.move_id]) {
                total += this.requestQtyOf(line) || 0;
            }
        }
        return total;
    }

    async onCreateRequest() {
        const moveIds = Object.keys(this.state.selected)
            .filter((k) => this.state.selected[k])
            .map((k) => parseInt(k, 10));
        if (!moveIds.length) {
            return;
        }
        const moveQuantities = {};
        for (const mid of moveIds) {
            const q = this.state.requestQty[mid];
            moveQuantities[mid] = q === undefined ? 0 : q;
        }
        this.state.creating = true;
        try {
            const res = await this.orm.call(
                "mrp.purchase.need", "create_purchase_request", [], {
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

    onSearchInput(ev) {
        const query = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(async () => {
            this.state.query = query;
            await this.loadGroups();
        }, SEARCH_DELAY);
    }

    async onWarehouseChange(ev) {
        this.state.warehouseId = ev.target.value ? parseInt(ev.target.value, 10) : false;
        this.state.lines = {};
        await this.loadGroups();
    }

    async onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        await this.loadGroups();
    }

    async onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        await this.loadGroups();
    }

    onUncoveredChange(ev) {
        this.state.uncoveredOnly = ev.target.checked;
    }

    onLateChange(ev) {
        this.state.lateOnly = ev.target.checked;
    }

    onSourceToggle(ev) {
        this.state.showSource = ev.target.checked;
    }

    onMipToggle(ev) {
        this.state.showMip = ev.target.checked;
    }

    toggleColsMenu() {
        this.state.colsOpen = !this.state.colsOpen;
    }

    onSortChange(ev) {
        this.state.sortBy = ev.target.value;
    }

    // -- rendering helpers ------------------------------------------------

    fmtQty(value) {
        return formatFloat(value || 0, { digits: [16, 2] });
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
        return !!this.state.selected[line.move_id];
    }

    groupLines(group) {
        return this.state.lines[group.product_id] || [];
    }

    groupSuggestions(group) {
        return this.state.suggestions[group.product_id] || [];
    }

    openSuggestions(group) {
        this.dialog.add(SuggestionsDialog, {
            suggestions: this.groupSuggestions(group),
            openOrder: (sug) => this.openOrder(sug),
            fmtDate: (d) => this.fmtDate(d),
            fmtQty: (q) => this.fmtQty(q),
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
        } else if (line.requested_qty > 0 && line.requestable_qty <= 0) {
            cls += " o_mnp_requested";
        } else if (line.is_late) {
            cls += " o_mnp_late";
        }
        return cls;
    }
}

registry.category("actions").add("mrp_purchase_need_plan.screen", NeedPlan);
