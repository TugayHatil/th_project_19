/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";

const SEARCH_DELAY = 350;
const pad2 = (n) => String(n).padStart(2, "0");

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
            workcenterId: false,
            query: "",
            overloadOnly: false,
            rows: [],
        });
        this._searchTimer = null;
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

    // Totals are computed over the rows currently shown, so every active
    // filter re-aggregates the row automatically (AC-11).
    get totals() {
        return this.state.periods.map((p, i) => {
            const sum = { cap_h: 0, load_h: 0, diff_h: 0, cap_d: 0, load_d: 0, diff_d: 0 };
            for (const row of this.state.rows) {
                const cell = row.cells[i];
                for (const key of Object.keys(sum)) {
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
                    workcenter_id: this.state.workcenterId || false,
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

    async onWorkcenterChange(ev) {
        this.state.workcenterId = ev.target.value ? parseInt(ev.target.value, 10) : false;
        await this.loadGrid();
    }

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

    // -- rendering helpers ------------------------------------------------

    fmt(value, signed = false) {
        const text = formatFloat(Math.abs(value || 0), { digits: [16, 1] });
        if (!signed) {
            return formatFloat(value || 0, { digits: [16, 1] });
        }
        return `${value >= 0 ? "+" : "−"}${text}`;
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
