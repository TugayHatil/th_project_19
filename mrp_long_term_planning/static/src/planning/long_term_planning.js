/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { session } from "@web/session";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { formatFloat } from "@web/core/utils/numbers";
import { Pager } from "@web/core/pager/pager";

const SUB_COLS = ["os", "sm", "gm", "im", "pm", "ds"];
const PAGE_LIMIT = 80;
const SEARCH_DELAY = 350;

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
        });
        this._searchTimer = null;
        // focuses the [autofocus] PM input as soon as it is rendered
        useAutofocus();
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
        return `${months[0].label} – ${months[months.length - 1].label}`;
    }

    get periodText() {
        return this.periodLabel ? `${_t("Period")}: ${this.periodLabel}` : "";
    }

    get subCols() {
        return SUB_COLS;
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
            const data = await this.orm.call("mrp.ltp.line", "get_planning_grid", [], {
                warehouse_id: this.state.warehouseId || false,
                category_id: this.state.categoryId || false,
                query: this.state.query || "",
                needs_only: this.state.needsOnly,
                offset: this.state.offset,
                limit: this.state.limit,
            });
            // periods come back with every load so a month roll-over is
            // picked up on refresh without reloading the filters
            this.state.periods = data.periods || [];
            this.state.rows = data.rows;
            this.state.total = data.total;
            this.state.editingKey = null;
        } catch (error) {
            this.notifyError(error, _t("Planning data could not be loaded."));
        } finally {
            this.state.loading = false;
        }
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
        await this.loadGrid();
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
        if (this.state.editingKey) {
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
                Object.assign(row, res.row);
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

    subCellClass(cell, key) {
        let cls = "o_ltp_td_num";
        if (key === "os") {
            cls += " o_ltp_month_start";
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
