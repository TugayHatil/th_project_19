/** @odoo-module **/

import { Component, onMounted, useExternalListener, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { session } from "@web/session";

const SEARCH_DELAY = 350;
const pad2 = (n) => String(n).padStart(2, "0");
const PAGE_SIZE = 80;

export class NeedCapacityPlanning extends Component {
    static template = "mrp_long_term_planning.NeedCapacityPlanning";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: false,
            periods: [],
            startPeriod: "",
            workcenters: [],
            workcenterIds: [],        // multi-select; empty = all
            query: "",
            overloadOnly: false,
            rows: [],
            total: 0,
            page: 0,
            wcMenuOpen: false,
            // inline window editing: {key, start, end}
            editRow: null,
        });
        this._searchTimer = null;
        useExternalListener(window, "click", (ev) => {
            if (!ev.target.closest(".o_nc_dd")) {
                this.state.wcMenuOpen = false;
            }
        });
        onMounted(async () => {
            await this.loadFilters();
            await this.loadGrid();
        });
    }

    rowKey(row) {
        return `${row.product_id}-${row.year}-${row.month}`;
    }

    get pageCount() {
        return Math.max(1, Math.ceil(this.state.total / PAGE_SIZE));
    }

    get pagerText() {
        const total = this.state.total;
        if (!total) {
            return "0 / 0";
        }
        const from = this.state.page * PAGE_SIZE + 1;
        const to = Math.min(total, from + PAGE_SIZE - 1);
        return `${from}-${to} / ${total}`;
    }

    get workcenterLabel() {
        const ids = this.state.workcenterIds;
        if (!ids.length) {
            return _t("All");
        }
        const names = this.state.workcenters
            .filter((wc) => ids.includes(wc.id))
            .map((wc) => wc.name);
        return names.length <= 2 ? names.join(", ") : _t("%s selected", names.length);
    }

    // -- data --------------------------------------------------------------

    notifyError(error, fallback) {
        this.notification.add(
            error.data?.message || error.message || fallback,
            { type: "danger" },
        );
    }

    async loadFilters() {
        try {
            const data = await this.orm.call(
                "mrp.ltp.need", "get_need_filters", []);
            this.state.periods = data.periods || [];
            this.state.workcenters = data.workcenters || [];
            const first = this.state.periods[0];
            if (first) {
                this.state.startPeriod = `${first.year}-${pad2(first.month)}`;
            }
        } catch (error) {
            this.notifyError(error, _t("Filters could not be loaded."));
        }
    }

    async loadGrid() {
        this.state.loading = true;
        this.state.editRow = null;
        try {
            let startYear = false, startMonth = false;
            if (this.state.startPeriod) {
                [startYear, startMonth] = this.state.startPeriod
                    .split("-").map(Number);
            }
            const data = await this.orm.call(
                "mrp.ltp.need", "get_need_grid", [], {
                    workcenter_ids: this.state.workcenterIds,
                    query: this.state.query || "",
                    overload_only: this.state.overloadOnly,
                    start_year: startYear,
                    start_month: startMonth,
                    offset: this.state.page * PAGE_SIZE,
                    limit: PAGE_SIZE,
                });
            this.state.periods = data.periods || [];
            this.state.rows = data.rows;
            this.state.total = data.total;
        } catch (error) {
            this.notifyError(error, _t("Need data could not be loaded."));
        } finally {
            this.state.loading = false;
        }
    }

    // -- toolbar -------------------------------------------------------------

    async onStartPeriodChange(ev) {
        this.state.startPeriod = ev.target.value || "";
        this.state.page = 0;
        await this.loadGrid();
    }

    onSearchInput(ev) {
        const query = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(async () => {
            this.state.query = query;
            this.state.page = 0;
            await this.loadGrid();
        }, SEARCH_DELAY);
    }

    async onOverloadOnlyChange(ev) {
        this.state.overloadOnly = ev.target.checked;
        this.state.page = 0;
        await this.loadGrid();
    }

    toggleWcMenu() {
        this.state.wcMenuOpen = !this.state.wcMenuOpen;
    }

    isWorkcenterSelected(id) {
        return this.state.workcenterIds.includes(id);
    }

    async toggleWorkcenter(id) {
        const idx = this.state.workcenterIds.indexOf(id);
        if (idx >= 0) {
            this.state.workcenterIds.splice(idx, 1);
        } else {
            this.state.workcenterIds.push(id);
        }
        this.state.page = 0;
        await this.loadGrid();
    }

    async clearWorkcenters() {
        this.state.workcenterIds = [];
        this.state.page = 0;
        await this.loadGrid();
    }

    async prevPage() {
        if (this.state.page > 0) {
            this.state.page -= 1;
            await this.loadGrid();
        }
    }

    async nextPage() {
        if (this.state.page < this.pageCount - 1) {
            this.state.page += 1;
            await this.loadGrid();
        }
    }

    // -- inline schedule editing ------------------------------------------------

    isEditing(row) {
        return !!this.state.editRow
            && this.state.editRow.key === this.rowKey(row);
    }

    startEdit(row) {
        this.state.editRow = {
            key: this.rowKey(row),
            product_id: row.product_id,
            year: row.year,
            month: row.month,
            start: row.start || "",
            end: row.end || "",
        };
    }

    cancelEdit() {
        this.state.editRow = null;
    }

    onEditDate(field, ev) {
        this.state.editRow[field] = ev.target.value;
    }

    async saveEdit() {
        const edit = this.state.editRow;
        if (!edit) {
            return;
        }
        if (!edit.start || !edit.end || edit.end < edit.start) {
            this.notification.add(
                _t("Enter a valid start/end window."), { type: "warning" });
            return;
        }
        try {
            await this.orm.call(
                "mrp.ltp.need", "set_need_schedule", [], {
                    product_id: edit.product_id,
                    year: edit.year,
                    month: edit.month,
                    planned_start: edit.start,
                    planned_end: edit.end,
                });
            this.notification.add(
                _t("Planned window saved."), { type: "success" });
            await this.loadGrid();
        } catch (error) {
            this.notifyError(error, _t("Window could not be saved."));
        }
    }

    async clearPlan(row) {
        try {
            await this.orm.call(
                "mrp.ltp.need", "clear_need_schedule", [], {
                    product_id: row.product_id,
                    year: row.year,
                    month: row.month,
                });
            await this.loadGrid();
        } catch (error) {
            this.notifyError(error, _t("Window could not be cleared."));
        }
    }

    // -- rendering helpers -------------------------------------------------------

    fmtQty(value) {
        return formatFloat(value || 0, { digits: [16, 2] });
    }

    fmtHours(value) {
        return formatFloat(value || 0, { digits: [16, 1] });
    }

    fmtDate(value) {
        if (!value) {
            return "";
        }
        const lang = (session.user_context?.lang || "en_US").replace("_", "-");
        return new Intl.DateTimeFormat(lang, { dateStyle: "short" })
            .format(new Date(value));
    }

    statusLabel(row) {
        return {
            ok: _t("On Time"),
            late: _t("Overload"),
            planned: _t("Planned"),
            planned_late: _t("Planned · Late"),
            missing: _t("No Operations"),
        }[row.status] || row.status;
    }

    statusClass(row) {
        return "badge " + ({
            ok: "text-bg-success",
            late: "text-bg-danger",
            planned: "text-bg-primary",
            planned_late: "text-bg-warning",
            missing: "text-bg-secondary",
        }[row.status] || "text-bg-secondary");
    }
}

registry.category("actions").add(
    "mrp_long_term_planning.need", NeedCapacityPlanning);
