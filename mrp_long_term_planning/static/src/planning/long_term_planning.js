/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { session } from "@web/session";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { Pager } from "@web/core/pager/pager";

// Live month sub-columns: the SİPARİŞ group (Teyitli / Sipariş / Değişim —
// baseline vs live order comparison, BRD §3) followed by the metrics.
const ORDER_GROUP_COLS = [
    { key: "teyitli", label: _t("Confirmed") },
    { key: "os", label: _t("Order") },
    { key: "delta", label: _t("Change") },
];
const METRIC_COLS = [
    { key: "sm", label: _t("Stock") },
    { key: "gm", label: _t("Supply") },
    { key: "im", label: _t("Need") },
    { key: "pm", label: _t("Plan") },
    { key: "ds", label: _t("Projected") },
];
const HISTORY_COLS = [
    { key: "os", label: _t("Confirmed") },
    { key: "os2", label: _t("Order") },
    { key: "pm", label: _t("Plan") },
];
const PAGE_LIMIT = 80;
const SEARCH_DELAY = 350;
const EPS = 1e-6;

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

export class LongTermPlanning extends Component {
    static template = "mrp_long_term_planning.LongTermPlanning";
    static components = { Pager };
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: false,
            // rolling 12-month window, always supplied by the server —
            // never hard-coded in the frontend (BRD revision §5/§7)
            periods: [],
            qtyPrecision: 2,
            categories: [],
            warehouses: [],
            categoryId: false,
            warehouseId: false,
            query: "",
            needsOnly: false,
            offset: 0,
            limit: PAGE_LIMIT,
            total: 0,
            rows: [],
            editingKey: null,
            editValue: "",
            // -- baseline / revision state (BRD §5-§19) --
            revisions: [],       // dropdown list for the current scope
            baselineRev: null,   // header of the latest confirmed revision
            baselineMap: {},     // "pid:yyyymm" -> {os, pm, demand}
            viewMode: "live",    // live | history | compare
            historyId: false,
            historyData: null,   // {revision, periods, rows}
            compareA: false,     // revision id
            compareB: "live",    // "live" or revision id
            compareData: null,   // {a, b, periods, rows}
            changedOnly: false,  // §17
        });
        this._searchTimer = null;
        // focuses the [autofocus] PM input as soon as it is rendered
        useAutofocus();
        onMounted(async () => {
            await this.loadFilters();
            await Promise.all([this.loadGrid(), this.loadRevisions()]);
        });
    }

    // -- periods / headers -------------------------------------------------

    get activePeriods() {
        if (this.state.viewMode === "history" && this.state.historyData) {
            return this.state.historyData.periods;
        }
        if (this.state.viewMode === "compare" && this.state.compareData) {
            return this.state.compareData.periods;
        }
        return this.state.periods;
    }

    get months() {
        const fmt = monthFormatter();
        return this.activePeriods.map((p) => ({
            key: `${p.year}-${p.month}`,
            label: fmt.format(new Date(p.year, p.month - 1, 1)),
        }));
    }

    get periodLabel() {
        const months = this.months;
        if (!months.length) {
            return "";
        }
        return `${months[0].label} – ${months[months.length - 1].label}`;
    }

    get periodText() {
        return this.periodLabel ? `${_t("Period")}: ${this.periodLabel}` : "";
    }

    get orderGroupCols() {
        return ORDER_GROUP_COLS;
    }

    get metricCols() {
        return METRIC_COLS;
    }

    get historyCols() {
        return HISTORY_COLS;
    }

    get compareCols() {
        const data = this.state.compareData;
        return [
            { key: "a", label: data ? this.revLabel(data.a) : "" },
            { key: "b", label: data ? this.revLabel(data.b) : "" },
            { key: "delta", label: _t("Change") },
        ];
    }

    get isLive() {
        return this.state.viewMode === "live";
    }

    get isHistory() {
        return this.state.viewMode === "history";
    }

    get isCompare() {
        return this.state.viewMode === "compare";
    }

    get liveRows() {
        return this.state.rows;
    }

    get historyRows() {
        return this.state.historyData ? this.state.historyData.rows : [];
    }

    get compareRows() {
        const data = this.state.compareData;
        if (!data) {
            return [];
        }
        if (!this.state.changedOnly) {
            return data.rows;
        }
        // §17: hide rows whose delta is zero in every month
        return data.rows.filter((row) =>
            row.cells.some((cell) => Math.abs(cell.delta) > EPS));
    }

    get visibleRows() {
        if (this.isHistory) {
            return this.historyRows;
        }
        if (this.isCompare) {
            return this.compareRows;
        }
        return this.state.rows;
    }

    get lastConfirmText() {
        const rev = this.state.baselineRev;
        if (!rev) {
            return _t("Last confirm: —");
        }
        return `${_t("Last confirm")}: ${_t("Revision")} ${rev.name} · ${this.fmtDate(rev.date)}`;
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
            const data = await this.orm.call("mrp.ltp.line", "get_planning_filters", []);
            this.state.periods = data.periods || [];
            if (typeof data.qty_precision === "number") {
                this.state.qtyPrecision = data.qty_precision;
            }
            this.state.categories = data.categories || [];
            this.state.warehouses = data.warehouses || [];
        } catch (error) {
            this.notifyError(error, _t("Filters could not be loaded."));
        }
    }

    async loadGrid() {
        this.state.loading = true;
        try {
            const [data, baseline] = await Promise.all([
                this.orm.call("mrp.ltp.line", "get_planning_grid", [], {
                    warehouse_id: this.state.warehouseId || false,
                    category_id: this.state.categoryId || false,
                    query: this.state.query || "",
                    needs_only: this.state.needsOnly,
                    offset: this.state.offset,
                    limit: this.state.limit,
                }),
                this.orm.call("mrp.ltp.line", "get_baseline", [], {
                    warehouse_id: this.state.warehouseId || false,
                }),
            ]);
            // periods come back with every load so a month roll-over is
            // picked up on refresh without reloading the filters
            this.state.periods = data.periods || [];
            this.state.baselineRev = baseline.revision || null;
            this.state.baselineMap = baseline.lines || {};
            this.state.rows = this.mergeBaseline(data.rows);
            this.state.total = data.total;
            this.state.editingKey = null;
        } catch (error) {
            this.notifyError(error, _t("Planning data could not be loaded."));
        } finally {
            this.state.loading = false;
        }
    }

    // Merge the latest baseline into live cells: teyitli = order qty frozen
    // at the last confirm, delta = live order - teyitli (§2.3). null when
    // no baseline exists yet.
    mergeBaseline(rows) {
        const map = this.state.baselineMap;
        for (const row of rows) {
            for (const cell of row.cells) {
                const snap = map[`${row.product_id}:${cell.year * 100 + cell.month}`];
                cell.teyitli = snap ? snap.os : null;
                cell.delta = snap ? cell.os - snap.os : null;
            }
        }
        return rows;
    }

    async loadRevisions() {
        try {
            this.state.revisions = await this.orm.call(
                "mrp.ltp.line", "get_revision_list", [], {
                    warehouse_id: this.state.warehouseId || false,
                });
        } catch (error) {
            this.notifyError(error, _t("Revisions could not be loaded."));
        }
    }

    async onConfirmPlan() {
        this.state.loading = true;
        try {
            const res = await this.orm.call("mrp.ltp.line", "confirm_plan", [], {
                warehouse_id: this.state.warehouseId || false,
                category_id: this.state.categoryId || false,
                query: this.state.query || "",
            });
            const rev = res.revision;
            this.notification.add(
                `${_t("Revision")} ${rev.name} ${_t("created.")}`,
                { type: "success" },
            );
            await Promise.all([this.loadRevisions(), this.loadGrid()]);
        } catch (error) {
            this.notifyError(error, _t("The plan could not be confirmed."));
        } finally {
            this.state.loading = false;
        }
    }

    // -- view modes --------------------------------------------------------

    revLabel(rev) {
        if (!rev || !rev.id) {
            return _t("Current Plan");
        }
        return `${_t("Revision")} ${rev.name}`;
    }

    async onRevisionChange(ev) {
        const value = ev.target.value;
        if (!value) {
            this.state.viewMode = "live";
            this.state.historyId = false;
            this.state.historyData = null;
            return;
        }
        this.state.historyId = parseInt(value, 10);
        await this.loadHistory();
    }

    async loadHistory() {
        this.state.loading = true;
        try {
            this.state.historyData = await this.orm.call(
                "mrp.ltp.line", "get_revision_data", [], {
                    revision_id: this.state.historyId,
                });
            this.state.viewMode = "history";
        } catch (error) {
            this.notifyError(error, _t("Revision could not be loaded."));
        } finally {
            this.state.loading = false;
        }
    }

    async onCompareWithCurrent() {
        this.state.compareA = this.state.historyId;
        this.state.compareB = "live";
        await this.loadCompare();
    }

    async onCompareAChange(ev) {
        this.state.compareA = ev.target.value ? parseInt(ev.target.value, 10) : false;
        if (this.state.compareA) {
            await this.loadCompare();
        }
    }

    async onCompareBChange(ev) {
        const value = ev.target.value;
        this.state.compareB = value === "live" ? "live" : parseInt(value, 10);
        await this.loadCompare();
    }

    async loadCompare() {
        if (!this.state.compareA) {
            return;
        }
        this.state.loading = true;
        try {
            this.state.compareData = await this.orm.call(
                "mrp.ltp.line", "get_compare_data", [], {
                    rev_a_id: this.state.compareA,
                    rev_b_id: this.state.compareB === "live"
                        ? false : this.state.compareB,
                    warehouse_id: this.state.warehouseId || false,
                    category_id: this.state.categoryId || false,
                    query: this.state.query || "",
                });
            this.state.viewMode = "compare";
            this.state.historyId = false;
        } catch (error) {
            this.notifyError(error, _t("Comparison could not be loaded."));
        } finally {
            this.state.loading = false;
        }
    }

    onChangedOnlyChange(ev) {
        this.state.changedOnly = ev.target.checked;
    }

    backToLive() {
        this.state.viewMode = "live";
        this.state.historyId = false;
        this.state.historyData = null;
        this.state.compareData = null;
    }

    // -- toolbar ----------------------------------------------------------

    async onCategoryChange(ev) {
        this.state.categoryId = ev.target.value ? parseInt(ev.target.value, 10) : false;
        this.state.offset = 0;
        await this.loadGrid();
    }

    async onWarehouseChange(ev) {
        this.state.warehouseId = ev.target.value ? parseInt(ev.target.value, 10) : false;
        this.state.offset = 0;
        // baselines and revisions are scoped per warehouse — reload both
        await Promise.all([this.loadGrid(), this.loadRevisions()]);
    }

    onSearchInput(ev) {
        const query = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(async () => {
            this.state.query = query;
            this.state.offset = 0;
            await this.loadGrid();
        }, SEARCH_DELAY);
    }

    async onNeedsOnlyChange(ev) {
        this.state.needsOnly = ev.target.checked;
        this.state.offset = 0;
        await this.loadGrid();
    }

    async onPagerUpdate({ offset, limit }) {
        this.state.offset = offset;
        this.state.limit = limit;
        await this.loadGrid();
    }

    // -- PM editing -------------------------------------------------------

    editKey(row, cell) {
        return `${row.product_id}:${cell.year}-${cell.month}`;
    }

    isEditing(row, cell) {
        return this.state.editingKey === this.editKey(row, cell);
    }

    startEdit(row, cell) {
        if (this.state.editingKey || !this.isLive) {
            return;
        }
        this.state.editingKey = this.editKey(row, cell);
        this.state.editValue = cell.pm ? String(cell.pm) : "";
    }

    cancelEdit() {
        this.state.editingKey = null;
    }

    onEditInput(ev) {
        this.state.editValue = ev.target.value;
    }

    onEditKeydown(row, cell, ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.commitEdit(row, cell);
        } else if (ev.key === "Escape") {
            ev.stopPropagation();
            this.cancelEdit();
        }
    }

    async commitEdit(row, cell) {
        if (this.state.editingKey !== this.editKey(row, cell)) {
            return;
        }
        const parsed = parseFloat(this.state.editValue);
        const qty = Number.isNaN(parsed) ? 0 : Math.max(0, parsed);
        this.state.editingKey = null;
        if (qty === cell.pm) {
            return;
        }
        try {
            const res = await this.orm.call("mrp.ltp.line", "set_planned_qty", [], {
                product_id: row.product_id,
                year: cell.year,
                month: cell.month,
                warehouse_id: this.state.warehouseId || false,
                planned_qty: qty,
            });
            if (res.row) {
                // keep the baseline merge alive on the refreshed row
                Object.assign(row, this.mergeBaseline([res.row])[0]);
            }
        } catch (error) {
            this.notifyError(error, _t("The planned quantity could not be saved."));
        }
    }

    // -- rendering helpers ------------------------------------------------

    fmtQty(value) {
        // digits come from the "Long-Term Planning Quantity" entry in
        // decimal.precision so the planner can tune them per database
        return formatFloat(value || 0, { digits: [16, this.state.qtyPrecision] });
    }

    fmtDelta(delta) {
        // §12: ↑ +N / ↓ -N / — for zero or missing baseline
        if (delta === null || delta === undefined || Math.abs(delta) < EPS) {
            return "—";
        }
        const qty = this.fmtQty(Math.abs(delta));
        return delta > 0 ? `↑ +${qty}` : `↓ −${qty}`;
    }

    deltaClass(delta, moIndex) {
        let cls = "o_ltp_td_num";
        if (moIndex % 2) {
            cls += " o_ltp_alt";
        }
        if (delta === null || delta === undefined || Math.abs(delta) < EPS) {
            cls += " text-muted";
        } else if (delta > 0) {
            cls += " o_ltp_delta_pos";
        } else {
            cls += " o_ltp_delta_neg";
        }
        return cls;
    }

    fmtDate(value) {
        if (!value) {
            return "";
        }
        const lang = (session.user_context?.lang || "en_US").replace("_", "-");
        return new Intl.DateTimeFormat(lang, { dateStyle: "short" })
            .format(new Date(value));
    }

    subCellClass(cell, key, moIndex) {
        let cls = "o_ltp_td_num";
        if (key === "teyitli" || key === "os" || key === "a") {
            cls += " o_ltp_month_start";
        }
        if (moIndex % 2) {
            cls += " o_ltp_alt";
        }
        if (key === "pm") {
            cls += " o_ltp_pm";
        } else if ((cell[key] || 0) === 0) {
            cls += " text-muted";
        }
        if (key === "im" && cell.im > 0) {
            cls += " o_ltp_need";
        } else if (key === "ds" && cell.ds < 0) {
            cls += " o_ltp_neg";
        }
        return cls;
    }
}

registry.category("actions").add("mrp_long_term_planning.screen", LongTermPlanning);
