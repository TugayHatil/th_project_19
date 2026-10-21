/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";

const SEARCH_DELAY = 350;

export class NeedPlan extends Component {
    static template = "mrp_purchase_need_plan.NeedPlan";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: false,
            creating: false,
            groups: [],
            // product_id -> need line list, filled lazily on expand (BRD §9)
            lines: {},
            expanded: {},
            selected: {},
            warehouses: [],
            warehouseId: false,
            dateFrom: "",
            dateTo: "",
            query: "",
            uncoveredOnly: false,
            lateOnly: false,
            sortBy: "purchase_start",
            canCreate: false,
            today: "",
        });
        this._searchTimer = null;
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
                    delete this.state.expanded[pid];
                    delete this.state.selected[pid];
                }
            }
        } catch (error) {
            this.notifyError(error, _t("Planlama verisi yüklenemedi."));
        } finally {
            this.state.loading = false;
        }
    }

    async toggleGroup(group) {
        const pid = group.product_id;
        if (this.state.expanded[pid]) {
            this.state.expanded[pid] = false;
            return;
        }
        this.state.expanded[pid] = true;
        if (this.state.lines[pid]) {
            return;
        }
        try {
            const data = await this.orm.call(
                "mrp.purchase.need", "get_need_lines", [], {
                    product_id: pid,
                    warehouse_id: this.state.warehouseId || false,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                });
            this.state.lines[pid] = data.lines || [];
            if (data.group) {
                // keep the header in sync with the lazily computed detail
                Object.assign(group, data.group);
            }
        } catch (error) {
            this.state.expanded[pid] = false;
            this.notifyError(error, _t("İhtiyaç detayları yüklenemedi."));
        }
    }

    toggleSelect(group, ev) {
        this.state.selected[group.product_id] = ev.target.checked;
    }

    async onCreateRequest() {
        const productIds = this.state.groups
            .filter((g) => this.state.selected[g.product_id])
            .map((g) => g.product_id);
        if (!productIds.length) {
            return;
        }
        this.state.creating = true;
        try {
            const res = await this.orm.call(
                "mrp.purchase.need", "create_purchase_request", [], {
                    product_ids: productIds,
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
        const lang = (session.user_context?.lang || "en_US").replace("_", "-");
        return new Intl.DateTimeFormat(lang, { dateStyle: "short" })
            .format(new Date(value));
    }

    isExpanded(group) {
        return !!this.state.expanded[group.product_id];
    }

    isSelected(group) {
        return !!this.state.selected[group.product_id];
    }

    groupLines(group) {
        return this.state.lines[group.product_id] || [];
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
        if (line.already_requested) {
            cls += " o_mnp_requested";
        } else if (line.uncovered_qty <= 0) {
            cls += " o_mnp_covered";
        } else if (line.is_late) {
            cls += " o_mnp_late";
        }
        return cls;
    }
}

registry.category("actions").add("mrp_purchase_need_plan.screen", NeedPlan);
