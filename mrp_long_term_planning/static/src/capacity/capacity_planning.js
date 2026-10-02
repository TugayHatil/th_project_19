/** @odoo-module **/

import { Component, onMounted, useExternalListener, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";

const SEARCH_DELAY = 350;
const pad2 = (n) => String(n).padStart(2, "0");

// Column catalogue (BRD §4) — global visibility, applied to every month.
const COLUMNS = [
    { key: "cap", label: _t("Capacity") },
    { key: "plan", label: _t("Planned Production") },
    { key: "rem", label: _t("Remaining Capacity") },
    { key: "req", label: _t("Required Production") },
    { key: "tot", label: _t("Total Workload") },
    { key: "diff", label: _t("Diff") },
];
const CELL_KEYS = ["cap_h", "cap_d", "plan_h", "plan_d", "rem_h", "rem_d",
    "req_h", "req_d", "tot_h", "tot_d", "diff_h", "diff_d"];

// Month labels follow the Odoo user's language, never the browser locale.
let monthFmt = null;
function monthFormatter() {
    if (!monthFmt) {
        let lang = "";
        try {
            lang = localization.code;
        } catch {
            // localization params not ready yet — fall back to the session
        }
        const locale = (lang || session.user_context?.lang || "en_US").replace("_", "-");
        monthFmt = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" });
    }
    return monthFmt;
}

export class CapacityPlanning extends Component {
    static template = "mrp_long_term_planning.CapacityPlanning";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: false,
            // rolling 12-month window supplied by the server; the start
            // month may be overridden by the user (BRD §5)
            periods: [],
            startPeriod: "",
            workcenters: [],
            workcenterIds: [],        // multi-select; empty = all
            query: "",
            overloadOnly: false,
            rows: [],
            visible: Object.fromEntries(COLUMNS.map((c) => [c.key, true])),
            // display units (BRD §2): days are derived from hours client-side
            showDays: true,
            showHours: true,
            colMenuOpen: false,
            wcMenuOpen: false,
        });
        this._searchTimer = null;
        this.COLUMNS = COLUMNS;
        // any click outside our dropdown panels closes them
        useExternalListener(window, "click", (ev) => {
            if (!ev.target.closest(".o_cap_dd")) {
                this.state.colMenuOpen = false;
                this.state.wcMenuOpen = false;
            }
        });
        onMounted(async () => {
            await this.loadFilters();
            await this.loadGrid();
        });
    }

    get months() {
        const fmt = monthFormatter();
        return this.state.periods.map((p) => ({
            key: `${p.year}-${p.month}`,
            label: fmt.format(new Date(p.year, p.month - 1, 1)),
        }));
    }

    get periodLabel() {
        const months = this.months;
        if (!months.length) {
            return "";
        }
        return `${months[0].label} → ${months[months.length - 1].label}`;
    }

    get periodText() {
        return this.periodLabel ? `${_t("Period")}: ${this.periodLabel}` : "";
    }

    get activeCols() {
        return COLUMNS.filter((c) => this.state.visible[c.key]);
    }

    get colCount() {
        return Math.max(this.activeCols.length, 1);
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

    // Totals are computed over the rows currently shown, so every active
    // filter re-aggregates the row automatically (AC-11/§17).
    get totals() {
        return this.state.periods.map((p, i) => {
            const sum = Object.fromEntries(CELL_KEYS.map((k) => [k, 0]));
            for (const row of this.state.rows) {
                const cell = row.cells[i];
                for (const key of CELL_KEYS) {
                    sum[key] += cell[key];
                }
            }
            return sum;
        });
    }

    // -- data ------------------------------------------------------------

    notifyError(error, fallback) {
        this.notification.add(
            error.data?.message || error.message || fallback,
            { type: "danger" },
        );
    }

    async loadFilters() {
        try {
            const data = await this.orm.call(
                "mrp.ltp.capacity", "get_capacity_filters", []);
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
        try {
            let startYear = false, startMonth = false;
            if (this.state.startPeriod) {
                [startYear, startMonth] = this.state.startPeriod
                    .split("-").map(Number);
            }
            const data = await this.orm.call(
                "mrp.ltp.capacity", "get_capacity_grid", [], {
                    workcenter_ids: this.state.workcenterIds,
                    query: this.state.query || "",
                    overload_only: this.state.overloadOnly,
                    start_year: startYear,
                    start_month: startMonth,
                });
            this.state.periods = data.periods || [];
            this.state.rows = data.rows;
        } catch (error) {
            this.notifyError(error, _t("Capacity data could not be loaded."));
        } finally {
            this.state.loading = false;
        }
    }

    // -- toolbar ----------------------------------------------------------

    async onStartPeriodChange(ev) {
        this.state.startPeriod = ev.target.value || "";
        await this.loadGrid();
    }

    onSearchInput(ev) {
        const query = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(async () => {
            this.state.query = query;
            await this.loadGrid();
        }, SEARCH_DELAY);
    }

    async onOverloadOnlyChange(ev) {
        this.state.overloadOnly = ev.target.checked;
        await this.loadGrid();
    }

    toggleMenu(menu) {
        this.state[menu + "MenuOpen"] = !this.state[menu + "MenuOpen"];
        if (menu === "col") {
            this.state.wcMenuOpen = false;
        } else {
            this.state.colMenuOpen = false;
        }
    }

    async toggleColumn(key) {
        this.state.visible[key] = !this.state.visible[key];
    }

    // Unchecking both units would blank every cell — fall back to days+hours.
    toggleUnit(key) {
        this.state[key] = !this.state[key];
        if (!this.state.showDays && !this.state.showHours) {
            this.state.showDays = true;
            this.state.showHours = true;
        }
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
        await this.loadGrid();
    }

    async clearWorkcenters() {
        this.state.workcenterIds = [];
        await this.loadGrid();
    }

    // -- rendering helpers ------------------------------------------------

    fmt(value, signed = false) {
        if (!signed) {
            return formatFloat(value || 0, { digits: [16, 1] });
        }
        const abs = formatFloat(Math.abs(value || 0), { digits: [16, 1] });
        return `${value >= 0 ? "+" : "−"}${abs}`;
    }

    cellText(cell, col, unit) {
        const value = cell[`${col.key}_${unit}`] || 0;
        const suffix = unit === "d" ? ` ${_t("days")}` : ` ${_t("hrs")}`;
        return this.fmt(value, col.key === "diff") + suffix;
    }

    cellClass(cell, col) {
        let cls = "o_cap_td_num";
        if (col === this.activeCols[0]) {
            cls += " o_cap_month_start";
        }
        if (col.key === "diff" || col.key === "tot") {
            cls += ` ${this.diffClass(cell)}`;
        }
        return cls;
    }

    diffClass(cell) {
        if (cell.diff_h > 1e-6) {
            return "o_cap_pos";
        }
        if (cell.diff_h < -1e-6) {
            return "o_cap_neg";
        }
        return "o_cap_zero";
    }
}

registry.category("actions").add("mrp_long_term_planning.capacity", CapacityPlanning);
