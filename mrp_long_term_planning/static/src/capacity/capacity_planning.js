/** @odoo-module **/

import { Component, onMounted, onPatched, useExternalListener, useRef, useState } from "@odoo/owl";
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
    { key: "plan", label: _t("Production") },
    { key: "rem", label: _t("Remaining") },
    { key: "req", label: _t("Required") },
    { key: "tot", label: _t("Workload") },
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
            // inline capacity-factor editing: {wc, year, month} of the cell
            // being edited plus the raw input text
            editFactor: null,
            editValue: "",
            colMenuOpen: false,
            wcMenuOpen: false,
        });
        this.factorInput = useRef("factorInput");
        onPatched(() => {
            if (this.factorInput.el) {
                this.factorInput.el.focus();
                this.factorInput.el.select();
            }
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

    // +1: the fixed "Factor" column opens every month group (BRD §3)
    get colCount() {
        return this.activeCols.length + 1;
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

    // -- inline factor editing (BRD §4-§6, §13-14) -------------------------

    fmtFactor(value) {
        return (value ?? 1).toFixed(2).replace(".", ",");
    }

    // non-default factors are highlighted (kept out of the template:
    // the OWL compiler mis-tokenizes the 1e-6 literal)
    factorValClass(cell) {
        const modified = Math.abs((cell.factor || 1) - 1) > 1e-6;
        return "o_cap_factor_val" + (modified ? " o_cap_factor_mod" : "");
    }

    isEditingFactor(row, cell) {
        const edit = this.state.editFactor;
        return !!edit && edit.wc === row.workcenter_id
            && edit.year === cell.year && edit.month === cell.month;
    }

    startFactorEdit(row, cell) {
        this.state.editFactor = {
            wc: row.workcenter_id, year: cell.year, month: cell.month,
        };
        this.state.editValue = this.fmtFactor(cell.factor);
    }

    cancelFactorEdit() {
        this.state.editFactor = null;
    }

    onFactorInput(ev) {
        this.state.editValue = ev.target.value;
    }

    onFactorKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.commitFactor();
        } else if (ev.key === "Escape") {
            this.state.editFactor = null;
        }
    }

    async commitFactor() {
        const target = this.state.editFactor;
        if (!target) {
            return;
        }
        // Turkish decimal comma is the natural input — accept both
        const factor = parseFloat(
            (this.state.editValue || "").replace(",", "."));
        if (!Number.isFinite(factor) || factor <= 0) {
            this.notification.add(
                _t("Enter a positive factor, e.g. 1,20."), { type: "warning" });
            this.state.editFactor = null;
            return;
        }
        let startYear = false, startMonth = false;
        const first = this.state.periods[0];
        if (first) {
            [startYear, startMonth] = [first.year, first.month];
        }
        try {
            const res = await this.orm.call(
                "mrp.ltp.capacity", "set_capacity_factor", [], {
                    workcenter_id: target.wc,
                    year: target.year,
                    month: target.month,
                    factor,
                    start_year: startYear,
                    start_month: startMonth,
                });
            const row = this.state.rows.find(
                (r) => r.workcenter_id === target.wc);
            if (row && res.row) {
                Object.assign(row, res.row);
            }
        } catch (error) {
            this.notifyError(error, _t("Factor could not be saved."));
        } finally {
            this.state.editFactor = null;
        }
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
        const suffix = unit === "d" ? ` ${_t("d")}` : ` ${_t("h")}`;
        return this.fmt(value, col.key === "diff") + suffix;
    }

    cellClass(cell, col) {
        // the month boundary line is carried by the Factor column, not the
        // first metric column
        let cls = "o_cap_td_num";
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
