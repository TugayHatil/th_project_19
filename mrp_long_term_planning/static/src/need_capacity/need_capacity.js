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
        this.action = useService("action");
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
            // APS: selected need's op rows, all ops, gantt, run flag
            selectedKey: null,
            opsRows: [],
            allOps: [],
            familyRows: [],
            familyRoot: "",
            familyRange: {},
            familyView: "month",
            familyCols: [],
            familySel: null,
            gantt: { days: [], wcs: [] },
            planning: false,
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
        return `${row.product_id}-${row.key}`;
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
            line_key: row.key,
            start: row.start || "",
            end: row.end || "",
            capacity: row.capacity || 1,
        };
    }

    cancelEdit() {
        this.state.editRow = null;
    }

    onEditDate(field, ev) {
        this.state.editRow[field] = ev.target.value;
    }

    onEditCapacity(ev) {
        const v = parseFloat(ev.target.value);
        this.state.editRow.capacity = Number.isNaN(v) ? 1 : v;
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
                    line_key: edit.line_key,
                    planned_start: edit.start,
                    planned_end: edit.end,
                    capacity: edit.capacity || false,
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
                    line_key: row.key,
                });
            await this.loadGrid();
        } catch (error) {
            this.notifyError(error, _t("Window could not be cleared."));
        }
    }

    // -- APS ---------------------------------------------------------------

    async autoPlan() {
        this.state.planning = true;
        try {
            const res = await this.orm.call(
                "mrp.ltp.need", "auto_plan", []);
            this.notification.add(
                _t("Draft plan ready: %(p)s operations placed, %(s)s capacity shortage.",
                   { p: res.planned, s: res.shortage }),
                { type: res.shortage ? "warning" : "success" });
            await this.loadGrid();
            await this.loadOps();
        } catch (error) {
            this.notifyError(error, _t("Auto plan failed."));
        } finally {
            this.state.planning = false;
        }
    }

    async confirmPlan() {
        try {
            const res = await this.orm.call(
                "mrp.ltp.need", "confirm_operations", []);
            this.notification.add(
                _t("%s operations confirmed.", res.confirmed),
                { type: "success" });
            await this.loadOps();
        } catch (error) {
            this.notifyError(error, _t("Plan could not be confirmed."));
        }
    }

    async clearDrafts() {
        try {
            const res = await this.orm.call(
                "mrp.ltp.need", "clear_operation_drafts", []);
            this.notification.add(
                _t("%s draft rows cleared.", res.cleared),
                { type: "success" });
            await this.loadOps();
        } catch (error) {
            this.notifyError(error, _t("Drafts could not be cleared."));
        }
    }

    // product family timeline — the clicked need plus every need that
    // transitively explodes out of it (parent_keys chain)
    _familyOf(row) {
        const kids = {};
        for (const r of this.state.rows) {
            for (const pk of r.parent_keys || []) {
                (kids[pk] = kids[pk] || []).push(r);
            }
        }
        // walk to the family root first — clicking any member shows
        // the whole order family, not only the clicked subtree
        const byKey = {};
        for (const r of this.state.rows) {
            byKey[r.key] = r;
        }
        let root = row;
        for (let i = 0; i < 20; i++) {
            const up = (root.parent_keys || [])
                .map((k) => byKey[k]).find(Boolean);
            if (!up) {
                break;
            }
            root = up;
        }
        const fam = [];
        const seen = new Set([root.key]);
        const queue = [root];
        while (queue.length) {
            const n = queue.shift();
            fam.push(n);
            for (const c of kids[n.key] || []) {
                if (!seen.has(c.key)) {
                    seen.add(c.key);
                    queue.push(c);
                }
            }
        }
        fam.sort((a, b) => (a.depth - b.depth) ||
            (a.deadline || "").localeCompare(b.deadline || ""));
        const range = (r) => [
            (r.sch_start || r.planned_start || r.start || "").slice(0, 10),
            (r.sch_end || r.planned_end || r.end || "").slice(0, 10)];
        let mn = "9999-99", mx = "";
        for (const f of fam) {
            const [s, e] = range(f);
            if (s && s < mn) mn = s;
            if (e && e > mx) mx = e;
        }
        const DAY = 86400000;
        // columns: day mode → 24 hours of the earliest day, month mode
        // → every day of the spanned month(s), weekends shaded
        const cols = [];
        if (this.state.familyView === "day") {
            for (let h = 0; h < 24; h++) {
                cols.push({label: h, wknd: false});
            }
        } else {
            let d = new Date(mn.slice(0, 7) + "-01T00:00:00");
            const endYM = mx.slice(0, 7);
            const pad = (n) => String(n).padStart(2, "0");
            while (true) {
                const iso = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
                if (iso.slice(0, 7) > endYM) {
                    break;
                }
                const wd = d.getDay();
                cols.push({label: d.getDate(),
                    wknd: wd === 0 || wd === 6, iso});
                d = new Date(d.getTime() + DAY);
            }
        }
        this.state.familyCols = cols;
        const N = Math.max(cols.length, 1);
        this.state.familyRows = fam.map((f) => {
            const [s, e] = range(f);
            if (this.state.familyView === "day") {
                const D = this.state.familyDay || mn.slice(0, 10);
                if (!this.state.familyDay) {
                    this.state.familyDay = D;
                }
                let sH = null, eH = null;
                for (const o of this.state.allOps || []) {
                    if (o.line_key !== f.key || !o.planned_start) {
                        continue;
                    }
                    const os = o.planned_start.slice(0, 10);
                    const oe = (o.planned_end || "").slice(0, 10);
                    if (os > D || (oe && oe < D)) {
                        continue;
                    }
                    const hs = os === D
                        ? parseInt(o.planned_start.slice(11, 13), 10) : 0;
                    const he = oe === D
                        ? parseInt(o.planned_end.slice(11, 13), 10) + 1
                        : 24;
                    sH = sH === null ? hs : Math.min(sH, hs);
                    eH = eH === null ? he : Math.max(eH, he);
                }
                if (sH === null && s && e && s <= D && D <= e) {
                    sH = 0; eH = 24;
                }
                if (sH === null) {
                    return Object.assign({}, f,
                        {barLeft: 0, barWidth: 0, barText: "—"});
                }
                return Object.assign({}, f, {
                    barLeft: sH / 24 * 100,
                    barWidth: Math.max((eH - sH) / 24 * 100, 0.8),
                    barText: sH + ":00 → " + eH + ":00"});
            }
            // whatever the hour, start/end days render as full columns
            const startIdx = s ? Math.max(0, Math.floor(
                (new Date(s) - new Date(cols[0].iso)) / DAY)) : 0;
            const endIdx = e ? Math.max(startIdx, Math.floor(
                (new Date(e) - new Date(cols[0].iso)) / DAY)) : startIdx;
            return Object.assign({}, f, {
                barLeft: startIdx / N * 100,
                barWidth: Math.max((endIdx - startIdx + 1) / N * 100,
                    0.8),
                barText: s && e ? s.slice(5) + " → " + e.slice(5) : "—"});
        });
        this.state.familyRoot = root.name;
    }

    setFamilyView(v) {
        this.state.familyView = v;
        if (this.state.familySel) {
            this._familyOf(this.state.familySel);
        }
    }

    _shiftFamilyDay(delta) {
        if (!this.state.familyDay) {
            return;
        }
        const d = new Date(this.state.familyDay + "T00:00:00");
        d.setDate(d.getDate() + delta);
        const pad = (n) => String(n).padStart(2, "0");
        this.state.familyDay =
            `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
        if (this.state.familySel) {
            this._familyOf(this.state.familySel);
        }
    }

    async selectRow(row) {
        this.state.selectedKey = this.rowKey(row);
        this.state.familySel = row;
        this._familyOf(row);
        await this.loadOps();
    }

    async loadOps() {
        try {
            const rows = await this.orm.call(
                "mrp.ltp.need", "get_operation_rows", [], {});
            this.state.allOps = rows || [];
            const sel = (this.state.rows || []).find(
                (r) => this.rowKey(r) === this.state.selectedKey);
            this.state.opsRows = sel
                ? this.state.allOps.filter((r) => r.line_key === sel.key)
                : [];
            this.buildGantt(this.state.allOps);
            if (this.state.familySel) {
                this._familyOf(this.state.familySel);
            }
        } catch (error) {
            this.notifyError(error, _t("Operations could not be loaded."));
        }
    }

    buildGantt(ops) {
        const byWc = new Map();
        const daySet = new Set();
        for (const r of ops) {
            if (!r.planned_start || !r.planned_end || !r.workcenter_id) {
                continue;
            }
            if (!byWc.has(r.workcenter_id)) {
                byWc.set(r.workcenter_id,
                    { name: r.wc_name || "?", days: {} });
            }
            let d = new Date(r.planned_start.slice(0, 10));
            const de = new Date(r.planned_end.slice(0, 10));
            while (d <= de) {
                const ds = d.toISOString().slice(0, 10);
                daySet.add(ds);
                (byWc.get(r.workcenter_id).days[ds] ||= []).push(r);
                d.setDate(d.getDate() + 1);
            }
        }
        this.state.gantt = {
            days: [...daySet].sort().slice(0, 62),
            wcs: [...byWc.values()],
        };
    }

    openSo(soId, ev) {
        if (ev) {
            ev.preventDefault();
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: soId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onNeedCapacity(row, ev) {
        const cap = parseInt(ev.target.value, 10);
        ev.target.value = row.capacity || 1;
        if (!cap || cap < 1) {
            this.notification.add(
                _t("Parallel capacity must be a positive integer."),
                { type: "warning" });
            return;
        }
        try {
            await this.orm.call(
                "mrp.ltp.need", "set_need_capacity", [], {
                    product_id: row.product_id,
                    line_key: row.key,
                    capacity: cap,
                });
            await this.loadGrid();
        } catch (error) {
            this.notifyError(error, _t("Capacity could not be saved."));
        }
    }

    async toggleOpLock(op) {
        try {
            await this.orm.call(
                "mrp.ltp.need", "set_operation_lock", [], {
                    ids: [op.id], locked: !op.locked });
            await this.loadOps();
        } catch (error) {
            this.notifyError(error, _t("Lock could not be changed."));
        }
    }

    opStateClass(op) {
        return {
            draft: "text-bg-secondary", shortage: "text-bg-danger",
            confirmed: "text-bg-primary", done: "text-bg-success",
        }[op.state] || "text-bg-secondary";
    }

    opStateLabel(op) {
        return {
            draft: _t("Draft"), shortage: _t("Capacity Shortage"),
            confirmed: _t("Confirmed"), done: _t("Done"),
        }[op.state] || op.state;
    }

    fmtDateTime(v) {
        if (!v) {
            return "—";
        }
        const d = luxon.DateTime.fromSQL(v);
        return d.isValid ? d.toFormat("dd.MM.yy HH:mm") : v;
    }

    opDay(ds) {
        return ds ? ds.slice(8, 10) + "." + ds.slice(5, 7) : "";
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
