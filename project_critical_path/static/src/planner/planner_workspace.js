import { Component, onMounted, onPatched, useExternalListener, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

const DAY_MS = 86400000;
const SCALES = {
    day: { pxPerDay: 36, label: _t("Day") },
    week: { pxPerDay: 6, label: _t("Week") },
    month: { pxPerDay: 1.6, label: _t("Month") },
};
// Zoom = density multiplier per scale. The level 0 baseline is the
// fitted pxPerDay captured by fit(); each step multiplies it.
const ZOOM_FACTOR = 1.6;
const ZOOM_MIN = -3;
const ZOOM_MAX = 3;

// Selectable bar-info fields (BRD-17): at most BAR_INFO_MAX may be picked,
// the choice is remembered per project in localStorage.
const BAR_INFO_MAX = 3;
const BAR_INFO_STORE_KEY = "cp_planner_bar_info";
const BAR_INFO_DEFAULT = ["allocated_hours", "effective_hours", "progress"];
const BAR_INFO_FIELDS = [
    { key: "allocated_hours", label: _t("Planned Hours") },
    { key: "effective_hours", label: _t("Actual Hours") },
    { key: "progress", label: _t("Progress %") },
    { key: "date_start", label: _t("Start Date") },
    { key: "date_stop", label: _t("End Date") },
    { key: "name", label: _t("Task Name") },
];

const parseDay = (str) => {
    const [y, m, d] = str.split("-").map(Number);
    return new Date(y, m - 1, d);
};
// "YYYY-MM-DD HH:MM" local-time string used by the resource timeline.
const parseDt = (str) => {
    const [datePart, timePart = "00:00"] = str.split(" ");
    const [y, m, d] = datePart.split("-").map(Number);
    const [hh, mm] = timePart.split(":").map(Number);
    return new Date(y, m - 1, d, hh, mm);
};
const fmtDt = (date) =>
    `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
const addDays = (date, days) => new Date(date.getTime() + days * DAY_MS);
const dayDiff = (a, b) => Math.round((b.getTime() - a.getTime()) / DAY_MS);
const startOfWeek = (date) => addDays(date, -((date.getDay() + 6) % 7));
const startOfMonth = (date) => new Date(date.getFullYear(), date.getMonth(), 1);
const isoWeek = (date) => {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    d.setUTCDate(d.getUTCDate() + 3 - ((d.getUTCDay() + 6) % 7));
    const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
    return 1 + Math.round((d - firstThursday) / (7 * DAY_MS));
};
const pad2 = (n) => String(n).padStart(2, "0");
// All calendar labels follow the Odoo user's language (res.lang code), never
// the browser locale — the same assets serve every language. Built lazily:
// the localization service populates `localization` after module eval.
let calendarFormats = null;
function getCalendarFormats() {
    if (!calendarFormats) {
        let lang = "";
        try {
            lang = localization.code;
        } catch {
            // localization params are not ready yet — fall back to the session
        }
        const locale = (lang || session.user_context?.lang || "en_US").replace("_", "-");
        calendarFormats = {
            monthYear: new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }),
            dayMonth: new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }),
            mediumDate: new Intl.DateTimeFormat(locale, { dateStyle: "medium" }),
            compactDate: new Intl.DateTimeFormat(locale, { day: "2-digit", month: "2-digit", year: "2-digit" }),
            percent: new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }),
            number: new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
            weekdayShort: new Intl.DateTimeFormat(locale, { weekday: "short" }),
            dayCaption: new Intl.DateTimeFormat(locale, { weekday: "long", day: "numeric", month: "long" }),
            tipDate: new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" }),
            time: new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }),
            money: new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
        };
    }
    return calendarFormats;
}
const monthLabel = (date) => getCalendarFormats().monthYear.format(date);
const dayLabel = (date) => getCalendarFormats().dayMonth.format(date);
const isoDay = (date) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
// Must stay in sync with planner_workspace.scss row/bar metrics.
const PLANNER_ROW_H = 32;
const PLANNER_BAR_CENTER = 16;
const DEP_STUB = 12; // horizontal stub length next to each connected bar
const DEP_LANE = 6; // x offset between parallel connector lanes
const DEP_CORRIDOR_STEP = 4; // y fan-out step inside a row-gap corridor
const DEP_CORRIDOR_MAX = 6; // corridor offsets stay clear of the bars

export class PlannerWorkspace extends Component {
    static template = "project_critical_path.PlannerWorkspace";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.wbsRowsRef = useRef("wbsRows");
        this.ganttScrollRef = useRef("ganttScroll");
        const params = this.props.action?.params || {};
        const context = this.props.action?.context || {};
        this.state = useState({
            loading: true,
            projects: [],
            projectId: params.project_id || context.project_id || false,
            projectName: "",
            tasks: [],
            collapsedIds: new Set(),
            selectedId: null,
            scale: "week",
            pxPerDay: SCALES.week.pxPerDay,
            // Per-scale zoom levels (BRD Zoom Controls) — density only,
            // the time unit never changes. Level 0 = the fitted density.
            zoom: { day: 0, week: 0, month: 0 },
            // Continuous timeline: rangeStart/rangeEnd cover the task span
            // plus a per-scale buffer and grow on scroll/drag; the anchor
            // is only the navigation focus (Today, ‹ ›, date picker).
            rangeStart: null,
            rangeEnd: null,
            anchor: null,
            // Quick Inspector panel
            inspectorOpen: false,
            // When set, the Inspector shows an unsaved subtask draft for
            // this parent task id — the record is only created on Save.
            draftParentId: null,
            inspectorLoading: false,
            inspector: null,
            baseline: null,
            impact: null,
            depOpen: false,
            // BRD Dependency Lag: the arrow-click editor popover — holds
            // {taskId, predId, type, lag, unit, x, y} while open.
            depEdit: null,
            options: { stages: [], users: [] },
            form: null,
            saving: false,
            drag: null,
            // Baseline History panel
            historyOpen: false,
            historyLoading: false,
            historyList: [],
            historyDetail: null,
            historyDetailLoading: false,
            compareBaselineId: null,
            // Baseline Save inline form (BRD) — the user picks one of the
            // predefined active baseline titles for the new revision
            baselineSaveOpen: false,
            baselineSaveTitle: "",
            baselineTitles: [],
            baselineSaving: false,
            // Optional WBS date columns (BRD-19) — hidden by default
            colMenuOpen: false,
            showStartCol: false,
            showFinishCol: false,
            // Bar info field selector (BRD-17) — per-project selection
            barInfoOpen: false,
            barInfoKeys: [...BAR_INFO_DEFAULT],
            // Slack chip pinned left of each bar (BRD-18) — per-project toggle
            slackVisible: true,
            // Toolbar task search — the submitted text becomes a simple
            // name/wbs_code ilike domain sent with get_planner_data
            searchDomain: [],
            // Write access on project.task — checked once on mount; when
            // false, bar drags are blocked up-front with a warning instead
            // of silently reverting after a failed RPC.
            canEdit: true,
            // Resource Planning workspace modal (BRD-21)
            resModalOpen: false,
            resTask: null,
            resLoading: false,
            resData: null,
            resAddOpen: false,
            resEditingId: null,
            resForm: null,
            resSelReqId: null,
            resOptions: [],
            resOptionsLoading: false,
            resWindow: null,
            resRequired: null,
            resSelOptKey: null,
            // Timeline: scale, navigation anchor, live drag preview and the
            // pending assignment awaiting the explicit "Assign" commit (BRD-23)
            resTlScale: "week",
            resTlAnchor: null,
            resTlDrag: null,
            resTlPending: null,
            // Selected existing assignment + its edit/delete sub-state (BRD-24)
            resSelAssignId: null,
            resAssignEdit: null,
            resAssignDelConfirm: false,
            // Resource Board (BRD-19) — second workspace mode next to Planner
            boardMode: false,
            boardScale: "week",
            boardAnchor: null,
            boardLoading: false,
            boardResources: [],
            boardSelKey: null,
            boardGroupsCollapsed: new Set(),
            boardTip: null,
        });
        this.scales = SCALES;
        this._zoomBase = {}; // fitted pxPerDay per scale (zoom level 0)
        this.barInfoFields = BAR_INFO_FIELDS;
        this.resTlScales = { day: _t("Day"), week: _t("Week"), month: _t("Month") };
        useExternalListener(document.body, "keydown", (ev) => {
            if (ev.key !== "Escape") {
                return;
            }
            if (this.state.resModalOpen) {
                this.closeResourceWorkspace();
            } else if (this.state.inspectorOpen) {
                this.state.inspectorOpen = false;
            } else if (this.state.barInfoOpen) {
                this.state.barInfoOpen = false;
            } else if (this.state.historyOpen) {
                this.toggleHistory();
            } else if (this.state.colMenuOpen) {
                this.state.colMenuOpen = false;
            }
        });
        useExternalListener(document.body, "click", (ev) => {
            if (this.state.colMenuOpen && !ev.target.closest(".o_cp_planner_colmenu")) {
                this.state.colMenuOpen = false;
            }
        });
        // The gantt scroll element unmounts while the Resource Board is
        // shown — refit once it remounts so the timeline always fills
        // the viewport when returning to Planner.
        onPatched(() => {
            if (this._pendingFit) {
                this._pendingFit = false;
                this.fit();
            }
            if (this._leftExtendPx) {
                const el = this.ganttScrollRef.el;
                if (el) {
                    el.scrollLeft += this._leftExtendPx;
                }
                this._leftExtendPx = 0;
            }
            if (this._pendingScrollPx != null) {
                const el = this.ganttScrollRef.el;
                if (el) {
                    el.scrollLeft = Math.max(this._pendingScrollPx - 40, 0);
                }
                this._pendingScrollPx = null;
            }
            if (this._pendingZoomAnchor) {
                const el = this.ganttScrollRef.el;
                if (el) {
                    const anchor = this._pendingZoomAnchor;
                    const px = (anchor.ms - this.origin.getTime()) / DAY_MS
                        * this.state.pxPerDay;
                    el.scrollLeft = Math.max(px - anchor.frac * el.clientWidth, 0);
                }
                this._pendingZoomAnchor = null;
            }
        });
        onMounted(async () => {
            try {
                this.state.canEdit = await this.orm.call(
                    "project.task", "check_access_rights", ["write", false],
                );
            } catch {
                this.state.canEdit = true;
            }
            try {
                const info = await this.orm.call("project.project", "get_planner_projects", []);
                this.state.projects = info.projects || [];
            } catch {
                this.state.projects = [];
            }
            if (this.state.projectId) {
                await this.loadProject(this.state.projectId);
                // Open fitted to the viewport so the whole timeline is
                // visible without pressing Fit every time.
                this.fit();
            } else {
                this.state.loading = false;
            }
        });
    }

    async loadProject(projectId) {
        this.state.loading = true;
        this.loadBarInfoKeys();
        this.state.collapsedIds = new Set();
        this.state.selectedId = null;
        this.state.inspectorOpen = false;
        try {
            const kwargs = {};
            if (this.state.compareBaselineId) {
                kwargs.baseline_id = this.state.compareBaselineId;
            }
            if (this.state.searchDomain?.length) {
                kwargs.domain = this.state.searchDomain;
            }
            const data = await this.orm.call(
                "project.project", "get_planner_data", [projectId], kwargs,
            );
            this.state.projectName = data.project.name;
            this.state.tasks = data.tasks;
            this.computeRange();
        } catch (error) {
            this.state.tasks = [];
            this.notification.add(error.data?.message || _t("The planner data could not be loaded."), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    // Buffer days added on each side of the task span per scale — the
    // continuous timeline grows further on scroll/drag, so this is a
    // starting margin, not a hard bound.
    get rangeBufferDays() {
        return { day: 14, week: 42, month: 180 }[this.state.scale] || 42;
    }

    // Continuous timeline range: covers every task plus a scale-dependent
    // buffer on both ends, snapped to clean period boundaries so group
    // headers start aligned. The anchor is only a navigation focus — it
    // decides where ‹ › / Today / the picker scroll to, not what exists.
    computeRange() {
        const dates = [];
        for (const task of this.state.tasks) {
            if (task.date_start) {
                dates.push(parseDay(task.date_start));
            }
            if (task.date_stop) {
                dates.push(parseDay(task.date_stop));
            }
        }
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        let start = today;
        let end = today;
        for (const date of dates) {
            if (date < start) {
                start = date;
            }
            if (date > end) {
                end = date;
            }
        }
        const buffer = this.rangeBufferDays;
        this.state.rangeStart = this.snapRangeStart(addDays(start, -buffer));
        this.state.rangeEnd = this.snapRangeEnd(addDays(end, buffer));
        if (!this.state.anchor) {
            // Unsnapped on purpose — the initial scroll puts this date at
            // the viewport edge, so snapping to the period start could
            // leave the first task just out of view.
            this.state.anchor = today < start || today > end ? start : today;
        }
    }

    snapAnchor(date) {
        const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        if (this.state.scale === "month") {
            return startOfMonth(d);
        }
        if (this.state.scale === "week") {
            return startOfWeek(d);
        }
        return d;
    }

    snapRangeStart(date) {
        return this.snapAnchor(date);
    }

    // Exclusive end boundary — first day of the next period.
    snapRangeEnd(date) {
        const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        if (this.state.scale === "month") {
            return startOfMonth(new Date(d.getFullYear(), d.getMonth() + 1, 1));
        }
        if (this.state.scale === "week") {
            return addDays(startOfWeek(d), 7);
        }
        return addDays(d, 1);
    }

    // Continuous range — columns, bars, edges and the today marker all
    // share this origin; the range grows on scroll/drag, never on scale.
    get plannerRange() {
        const start = this.state.rangeStart || this.snapRangeStart(new Date());
        const end = this.state.rangeEnd || this.snapRangeEnd(new Date());
        return { start, end };
    }

    // Origin shared by columns, bars and the today marker so they stay aligned.
    get origin() {
        return this.plannerRange.start;
    }

    get taskById() {
        return new Map(this.state.tasks.map((task) => [task.id, task]));
    }

    get visibleTasks() {
        const { collapsedIds } = this.state;
        const byId = this.taskById;
        const hidden = new Set();
        for (const task of this.state.tasks) {
            let parent = byId.get(task.parent_id);
            while (parent) {
                if (collapsedIds.has(parent.id)) {
                    hidden.add(task.id);
                    break;
                }
                parent = byId.get(parent.parent_id);
            }
        }
        return this.state.tasks.filter((task) => !hidden.has(task.id));
    }

    // The cell list only depends on range/scale/density — during a drag it
    // changes only when the range extends, so keep the array stable to
    // avoid re-diffing thousands of nodes on every pointer move.
    get columns() {
        const range = this.plannerRange;
        const key = [
            this.state.scale,
            range.start.getTime(),
            range.end.getTime(),
            this.state.pxPerDay,
        ].join("|");
        if (this._colsKey === key) {
            return this._colsCache;
        }
        const cols = [];
        if (this.state.scale === "day") {
            // One hour cell per column across every day in the range.
            const hourWidth = this.state.pxPerDay / 24;
            for (let t = range.start.getTime(); t < range.end.getTime(); t += DAY_MS) {
                for (let h = 0; h < 24; h++) {
                    cols.push({ label: pad2(h), width: hourWidth });
                }
            }
        } else {
            const fmt = getCalendarFormats();
            for (let t = range.start.getTime(); t < range.end.getTime(); t += DAY_MS) {
                const d = new Date(t);
                cols.push({
                    label: this.state.scale === "month"
                        ? pad2(d.getDate())
                        : `${fmt.weekdayShort.format(d)} ${pad2(d.getDate())}`,
                    width: this.state.pxPerDay,
                });
            }
        }
        this._colsKey = key;
        this._colsCache = cols;
        return cols;
    }

    // Period headers above the day/hour cells — one group per day (day
    // scale), ISO week or calendar month, so boundaries stay visible as
    // the timeline scrolls continuously instead of ending at a page edge.
    get columnGroups() {
        const range = this.plannerRange;
        const key = [
            this.state.scale,
            range.start.getTime(),
            range.end.getTime(),
            this.state.pxPerDay,
        ].join("|");
        if (this._groupsKey === key) {
            return this._groupsCache;
        }
        const fmt = getCalendarFormats();
        const groups = [];
        const ppd = this.state.pxPerDay;
        let t = range.start.getTime();
        while (t < range.end.getTime()) {
            const d = new Date(t);
            let label;
            let next;
            if (this.state.scale === "month") {
                label = fmt.monthYear.format(d);
                next = startOfMonth(new Date(d.getFullYear(), d.getMonth() + 1, 1)).getTime();
            } else if (this.state.scale === "week") {
                label = `${fmt.monthYear.format(d)} · ${_t("Week")} ${isoWeek(d)}`;
                next = addDays(startOfWeek(d), 7).getTime();
            } else {
                label = fmt.dayCaption.format(d);
                next = t + DAY_MS;
            }
            const clipped = Math.min(next, range.end.getTime());
            groups.push({
                label,
                width: Math.max(dayDiff(d, new Date(clipped)) * ppd, ppd),
            });
            t = clipped;
        }
        this._groupsKey = key;
        this._groupsCache = groups;
        return groups;
    }

    get timelineWidth() {
        return Math.max(dayDiff(this.origin, this.plannerRange.end) * this.state.pxPerDay, 1);
    }

    get todayLeft() {
        const range = this.plannerRange;
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        if (today < range.start || today >= range.end) {
            return -9999;
        }
        const dayPx = dayDiff(range.start, today) * this.state.pxPerDay;
        if (this.state.scale === "day") {
            const now = new Date();
            return dayPx + ((now.getHours() + now.getMinutes() / 60) / 24) * this.state.pxPerDay;
        }
        return dayPx;
    }

    spanGeometry(startStr, stopStr, dtStart, dtStop) {
        if (!startStr || !stopStr) {
            return false;
        }
        const start = parseDay(startStr);
        const stop = parseDay(stopStr);
        const range = this.plannerRange;
        // Windowed view — bars fully outside the visible window are skipped
        // instead of being rendered at off-screen coordinates.
        if (stop < range.start || start >= range.end) {
            return false;
        }
        const ppd = this.state.pxPerDay;
        if (this.state.scale === "day") {
            // Hour precision across the continuous range: real stored
            // times when the payload carries them, otherwise the
            // 09:00–18:00 convention (same as the resource timelines).
            const originMs = range.start.getTime();
            const startMs = dtStart
                ? parseDt(dtStart).getTime()
                : start.getTime() + 9 * 3600000;
            const stopMs = dtStop
                ? parseDt(dtStop).getTime()
                : stop.getTime() + 18 * 3600000;
            const left = Math.max((startMs - originMs) / DAY_MS * ppd, 0);
            const right = Math.min((stopMs - originMs) / DAY_MS * ppd, this.timelineWidth);
            return { left, width: Math.max(right - left, 1) };
        }
        return {
            left: dayDiff(range.start, start) * ppd,
            width: Math.max(dayDiff(start, stop) + 1, 1) * ppd,
        };
    }

    // Overdue = planned finish before today (calendar-day granularity,
    // user-local) and the task is not Done. Progress never factors in;
    // during a drag the live stop date is used so the marker tracks.
    isOverdue(task) {
        if (task.is_done) {
            return false;
        }
        const stopStr = this.currentDates(task).stop;
        if (!stopStr) {
            return false;
        }
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        return parseDay(stopStr) < today;
    }

    // Toolbar task search — Enter submits; the planner reloads with a
    // name/wbs_code ilike domain (matching rows keep their WBS ancestors).
    // Clearing the input and pressing Enter again restores all tasks.
    async onTaskSearch(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const query = ev.target.value.trim();
        this.state.searchDomain = query
            ? ["|", ["name", "ilike", query], ["wbs_code", "ilike", query]]
            : [];
        if (this.state.projectId) {
            await this.loadProject(this.state.projectId);
        }
    }

    barTitle(task) {
        return task.is_critical ? `${task.name} — ${_t("Critical Path")}` : task.name;
    }

    resRoleLabel(role) {
        const stars = "★".repeat(role.priority || 0);
        const name = stars ? `${role.name} ${stars}` : role.name;
        return role.category === "equipment"
            ? `${name} (${_t("Equipment")})`
            : name;
    }

    starList(count) {
        return Array.from({ length: count || 0 }, (_, i) => i);
    }

    // The requirement level is the role's own 5-star level — it is shown
    // read-only and never picked manually in the planner (BRD §4).
    resFormRole() {
        const roleId = parseInt(this.state.resForm?.role_id, 10);
        return (this.state.resData?.roles || []).find((r) => r.id === roleId) || null;
    }

    resFormRate() {
        const roleId = parseInt(this.state.resForm?.role_id, 10);
        if (!roleId) {
            return null;
        }
        const rates = this.state.resData?.rates || [];
        const match = rates.find((r) => r.role_id === roleId)
            || rates.find((r) => r.role_id === null);
        return match ? match.hourly_rate : null;
    }

    resFormCost() {
        const rate = this.resFormRate();
        if (rate === null) {
            return null;
        }
        const qty = parseFloat(this.state.resForm?.quantity) || 0;
        const hours = parseFloat(this.state.resForm?.planned_hours) || 0;
        return qty * hours * rate;
    }

    resMoney(value) {
        const symbol = this.state.resData?.rate_template?.currency_symbol || "";
        const formatted = getCalendarFormats().money.format(value || 0);
        return symbol ? `${formatted} ${symbol}` : formatted;
    }

    onResFormRoleChange(value) {
        this.state.resForm.role_id = value;
    }

    // The dates the bar currently shows — during a drag this is the live
    // drag position so bars, variance tails and arrows follow the pointer.
    currentDates(task) {
        const drag = this.state.drag;
        if (drag && drag.taskId === task.id) {
            return { start: drag.start, stop: drag.stop };
        }
        return { start: task.date_start, stop: task.date_stop };
    }

    barGeometry(task) {
        const dates = this.currentDates(task);
        const drag = this.state.drag;
        const dragging = drag && drag.taskId === task.id;
        return this.spanGeometry(
            dates.start, dates.stop,
            dragging ? drag.dtStart : task.dt_start,
            dragging ? drag.dtStop : task.dt_stop,
        );
    }

    baselineStyle(task) {
        const bar = this.spanGeometry(task.baseline_start, task.baseline_stop);
        if (!bar) {
            return "display:none";
        }
        return `left:${bar.left}px;width:${bar.width}px`;
    }

    // Hatched tail: the part of the current bar beyond the baseline finish.
    // A same-duration shift or a duration increase both surface as a tail,
    // while a duration decrease shows only through the baseline ghost bar.
    varianceGeometry(task) {
        const dates = this.currentDates(task);
        if (this.state.scale === "day" || !dates.start || !dates.stop || !task.baseline_stop) {
            return false;
        }
        const extra = dayDiff(parseDay(task.baseline_stop), parseDay(dates.stop));
        if (extra <= 0) {
            return false;
        }
        const ppd = this.state.pxPerDay;
        const left = (dayDiff(this.origin, parseDay(task.baseline_stop)) + 1) * ppd;
        return { left, width: Math.max(extra * ppd, 1) };
    }

    varianceStyle(task) {
        const bar = this.varianceGeometry(task);
        if (!bar) {
            return "display:none";
        }
        return `left:${bar.left}px;width:${bar.width}px`;
    }

    baselineTooltip(task) {
        const days = dayDiff(parseDay(task.baseline_start), parseDay(task.baseline_stop));
        return `${_t("Baseline")} ${task.baseline_name}\n`
            + `${dayLabel(parseDay(task.baseline_start))} – ${dayLabel(parseDay(task.baseline_stop))}\n`
            + `${_t("Duration")}: ${days}d`;
    }

    varianceTooltip(task) {
        const stop = this.currentDates(task).stop;
        const days = dayDiff(parseDay(task.baseline_stop), parseDay(stop));
        return `${_t("Current finish")}: ${dayLabel(parseDay(stop))}\n${_t("Variance")}: +${days}d`;
    }

    barStyle(task) {
        const bar = this.barGeometry(task);
        if (!bar) {
            return "display:none";
        }
        return `left:${bar.left}px;width:${bar.width}px`;
    }

    // Finish-to-Start arrows between the rendered bars. Only edges whose two
    // endpoints are visible (not collapsed away) and scheduled are drawn.
    //
    // Routing: each connector leaves its predecessor on a distinct stub lane,
    // travels along the row-gap corridor next to the predecessor (fanned out
    // so parallel connectors do not share a horizontal), then drops on a
    // distinct entry lane into the successor bar's left edge. This keeps the
    // long runs inside empty channels instead of across task bars and stops
    // same-direction arrows from overlapping.
    get dependencyEdges() {
        const visible = this.visibleTasks;
        const indexById = new Map(visible.map((task, i) => [task.id, i]));
        const byId = this.taskById;
        const selected = this.state.selectedId;
        const raw = [];
        for (const task of visible) {
            const toBar = this.barGeometry(task);
            if (!toBar) {
                continue;
            }
            for (const dep of task.dependencies || []) {
                const predId = dep.task_id;
                const predIdx = indexById.get(predId);
                if (predIdx === undefined) {
                    continue; // predecessor collapsed or outside this project
                }
                const fromBar = this.barGeometry(byId.get(predId));
                if (!fromBar) {
                    continue;
                }
                raw.push({ predId, task, dep, predIdx, toIdx: indexById.get(task.id), fromBar, toBar });
            }
        }
        // Lane assignment: per-predecessor exit stubs, per-successor entry
        // stubs and a per-corridor vertical offset (the gap below row k is
        // shared by down-edges leaving row k and up-edges leaving row k+1).
        const outLanes = new Map();
        const inLanes = new Map();
        const corridorLanes = new Map();
        for (const edge of raw) {
            edge.outLane = outLanes.get(edge.predId) || 0;
            outLanes.set(edge.predId, edge.outLane + 1);
            edge.inLane = inLanes.get(edge.task.id) || 0;
            inLanes.set(edge.task.id, edge.inLane + 1);
            edge.down = edge.toIdx > edge.predIdx;
            edge.corridorKey = edge.down ? edge.predIdx : edge.predIdx - 1;
            edge.corridorLane = corridorLanes.get(edge.corridorKey) || 0;
            corridorLanes.set(edge.corridorKey, edge.corridorLane + 1);
        }
        const corridorCounts = new Map();
        for (const edge of raw) {
            corridorCounts.set(edge.corridorKey, (corridorCounts.get(edge.corridorKey) || 0) + 1);
        }
        return raw.map((edge) => {
            const x1 = edge.fromBar.left + edge.fromBar.width;
            const y1 = edge.predIdx * PLANNER_ROW_H + PLANNER_BAR_CENTER;
            // Arrows land left of the lead-in cluster (slack/!/✓) so the
            // markers stay readable instead of sitting under the arrowhead.
            const x2 = edge.toBar.left - this.barLeadWidth(edge.task);
            const y2 = edge.toIdx * PLANNER_ROW_H + PLANNER_BAR_CENTER;
            const exitX = x1 + DEP_STUB + edge.outLane * DEP_LANE;
            const entryX = x2 - DEP_STUB - edge.inLane * DEP_LANE;
            const count = corridorCounts.get(edge.corridorKey);
            const offset = Math.max(-DEP_CORRIDOR_MAX, Math.min(
                DEP_CORRIDOR_MAX, (edge.corridorLane - (count - 1) / 2) * DEP_CORRIDOR_STEP,
            ));
            const corridorY = y1 + (edge.down ? PLANNER_BAR_CENTER : -PLANNER_BAR_CENTER) + offset;
            const d = `M ${x1} ${y1} H ${exitX} V ${corridorY} H ${entryX} V ${y2} H ${x2}`;
            const related = selected === edge.task.id || selected === edge.predId;
            // BRD Dependency Lag: non-default edges get a small label on
            // the corridor segment — relationship type when it is not FS,
            // plus the signed lag ("SS +2d", "-4h", "+10h").
            const parts = [];
            if (edge.dep.type && edge.dep.type !== "fs") {
                parts.push(edge.dep.type.toUpperCase());
            }
            if (edge.dep.lag) {
                parts.push(
                    `${edge.dep.lag > 0 ? "+" : ""}${edge.dep.lag}${edge.dep.unit === "days" ? "d" : "h"}`,
                );
            }
            return {
                key: `${edge.predId}-${edge.task.id}`,
                taskId: edge.task.id,
                predId: edge.predId,
                d,
                arrowD: `M ${x2} ${y2} l -8 -4.5 l 0 9 z`,
                label: parts.length ? parts.join(" ") : null,
                labelX: (exitX + entryX) / 2,
                labelY: corridorY - 4,
                dim: Boolean(selected && !related),
                highlight: Boolean(selected && related),
                critical: Boolean(edge.task.is_critical && byId.get(edge.predId)?.is_critical),
            };
        });
    }

    setScale(scale) {
        if (this.state.scale === scale) {
            return;
        }
        this.state.scale = scale;
        this.state.anchor = this.snapAnchor(this.state.anchor || new Date());
        this.computeRange(); // buffer and snapping differ per scale
        this.fit();
    }

    // ‹ › move the focus one period through the continuous timeline; the
    // range auto-extends when the target lands outside the buffer.
    plannerNavigate(dir) {
        const base = this.state.anchor || new Date();
        if (this.state.scale === "month") {
            this.state.anchor = new Date(base.getFullYear(), base.getMonth() + dir, 1);
        } else {
            this.state.anchor = addDays(base, dir * (this.state.scale === "week" ? 7 : 1));
        }
        this.ensureRangeCovers(this.state.anchor);
        this.scrollToDate(this.state.anchor);
    }

    goToday() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        this.state.anchor = this.snapAnchor(today);
        this.ensureRangeCovers(this.state.anchor);
        this.scrollToDate(today);
    }

    get plannerPickerValue() {
        return isoDay(this.state.anchor || new Date());
    }

    onPlannerDatePick(ev) {
        const val = ev.target.value;
        if (!val) {
            return;
        }
        this.state.anchor = this.snapAnchor(parseDay(val));
        this.ensureRangeCovers(this.state.anchor);
        this.scrollToDate(parseDay(val));
    }

    // The scale only sets grid density — one period fills the viewport
    // (day → 24h, week → 7d, month → ~30d); the timeline keeps scrolling.
    // The fitted density is the zoom level-0 baseline for this scale.
    fit() {
        const el = this.ganttScrollRef.el;
        if (!el) {
            this._pendingFit = true;
            return;
        }
        const periodDays = { day: 1, week: 7, month: 30 }[this.state.scale] || 7;
        this._zoomBase[this.state.scale] = Math.min(
            Math.max((el.clientWidth - 4) / periodDays, 0.25), 2000,
        );
        this.state.pxPerDay = this.zoomDensity(this.state.scale);
        this.scrollToDate(this.state.anchor || new Date());
    }

    zoomDensity(scale) {
        const base = this._zoomBase[scale] || SCALES[scale].pxPerDay;
        return base * Math.pow(ZOOM_FACTOR, this.state.zoom[scale] || 0);
    }

    get zoomInDisabled() {
        return (this.state.zoom[this.state.scale] || 0) >= ZOOM_MAX;
    }

    get zoomOutDisabled() {
        return (this.state.zoom[this.state.scale] || 0) <= ZOOM_MIN;
    }

    zoomIn() {
        this.zoomBy(1);
    }

    zoomOut() {
        this.zoomBy(-1);
    }

    // Density change only — the scale and its time unit stay the same.
    // The datetime at the viewport centre is re-anchored after the patch
    // so the view does not jump to another date (see onPatched).
    zoomBy(dir) {
        const scale = this.state.scale;
        const level = Math.min(
            Math.max((this.state.zoom[scale] || 0) + dir, ZOOM_MIN), ZOOM_MAX,
        );
        if (level === (this.state.zoom[scale] || 0)) {
            return;
        }
        this.state.zoom[scale] = level;
        const el = this.ganttScrollRef.el;
        if (!el) {
            this.state.pxPerDay = this.zoomDensity(scale);
            return;
        }
        // Rapid consecutive presses keep the SAME datetime anchored —
        // the pending one already holds it until the patch lands.
        const pending = this._pendingZoomAnchor;
        const centerPx = el.scrollLeft + el.clientWidth / 2;
        this._pendingZoomAnchor = {
            ms: pending ? pending.ms
                : this.origin.getTime() + (centerPx / this.state.pxPerDay) * DAY_MS,
            frac: pending ? pending.frac : 0.5,
        };
        this.state.pxPerDay = this.zoomDensity(scale);
    }

    // Fit the whole dated task span into the viewport — picks the zoom
    // level closest to the required density, then anchors the project
    // start near the left edge. The scale's time unit never changes.
    fitTimeline() {
        const el = this.ganttScrollRef.el;
        let startMs = Infinity;
        let stopMs = -Infinity;
        for (const task of this.state.tasks) {
            const s = task.dt_start
                ? parseDt(task.dt_start).getTime()
                : task.date_start ? parseDay(task.date_start).getTime() : null;
            const e = task.dt_stop
                ? parseDt(task.dt_stop).getTime()
                : task.date_stop ? parseDay(task.date_stop).getTime() : null;
            if (s != null && s < startMs) {
                startMs = s;
            }
            if (e != null && e > stopMs) {
                stopMs = e;
            }
        }
        if (!el || !isFinite(startMs) || !isFinite(stopMs)) {
            return;
        }
        const spanDays = Math.max((stopMs - startMs) / DAY_MS, 1);
        const base = this._zoomBase[this.state.scale] || this.state.pxPerDay;
        const target = Math.max(el.clientWidth - 80, 200) / spanDays;
        const level = Math.min(Math.max(
            Math.round(Math.log(target / base) / Math.log(ZOOM_FACTOR)),
            ZOOM_MIN, ZOOM_MAX,
        ));
        this.state.zoom[this.state.scale] = level;
        const ppd = this.zoomDensity(this.state.scale);
        if (ppd === this.state.pxPerDay) {
            // No re-render — nothing will consume a pending anchor.
            const px = (startMs - this.origin.getTime()) / DAY_MS * ppd;
            el.scrollLeft = Math.max(px - 0.05 * el.clientWidth, 0);
        } else {
            this._pendingZoomAnchor = { ms: startMs, frac: 0.05 };
            this.state.pxPerDay = ppd;
        }
    }

    scrollToDate(date) {
        const el = this.ganttScrollRef.el;
        if (!el || !date) {
            return;
        }
        let px = dayDiff(this.origin, date) * this.state.pxPerDay;
        if (this.state.scale === "day") {
            px += ((date.getHours() + date.getMinutes() / 60) / 24) * this.state.pxPerDay;
        }
        const target = Math.max(px - 40, 0);
        el.scrollLeft = target;
        // The timeline widens asynchronously (state → patch). If the
        // target is beyond the current scrollable area the set above is
        // clamped — retry it once the patch has applied the new width.
        if (target > el.scrollWidth - el.clientWidth) {
            this._pendingScrollPx = px;
        }
    }

    // Grow the buffered range until it covers the given date — used by
    // nav, the picker and edge scrolling so nothing can land outside.
    // No scroll compensation here: the callers immediately scroll to an
    // absolute position in the new coordinate system.
    ensureRangeCovers(date) {
        let guard = 0;
        while (date < this.plannerRange.start && guard++ < 120) {
            this.extendRange("left", false);
        }
        guard = 0;
        while (date >= this.plannerRange.end && guard++ < 120) {
            this.extendRange("right", false);
        }
    }

    extendRange(direction, compensate = true) {
        if (!this.state.rangeStart || !this.state.rangeEnd) {
            this.computeRange();
            return;
        }
        const days = this.rangeBufferDays;
        if (direction === "right") {
            this.state.rangeEnd = this.snapRangeEnd(addDays(this.state.rangeEnd, days));
            return;
        }
        const oldStart = this.state.rangeStart;
        this.state.rangeStart = this.snapRangeStart(addDays(this.state.rangeStart, -days));
        if (!compensate) {
            return;
        }
        // Prepending shifts all content right — the patch compensates the
        // scroll position so the view does not jump (see onPatched).
        this._leftExtendPx = (this._leftExtendPx || 0)
            + dayDiff(this.state.rangeStart, oldStart) * this.state.pxPerDay;
    }

    toggleCollapse(task, ev) {
        ev.stopPropagation();
        const ids = new Set(this.state.collapsedIds);
        if (ids.has(task.id)) {
            ids.delete(task.id);
        } else {
            ids.add(task.id);
        }
        this.state.collapsedIds = ids;
    }

    async selectTask(task) {
        this.state.selectedId = task.id;
        this.state.inspectorOpen = true;
        await this.loadInspector(task.id);
    }

    async loadInspector(taskId) {
        this.state.inspectorLoading = true;
        try {
            const detail = await this.orm.call("project.task", "get_planner_detail", [taskId]);
            this.state.inspector = detail.task;
            this.state.baseline = detail.baseline;
            this.state.impact = detail.impact;
            this.state.options = detail.options;
            this.state.depOpen = false;
            this.state.draftParentId = null;
            const t = detail.task;
            this.state.form = {
                name: t.name,
                date_start: t.date_start || "",
                date_stop: t.date_stop || "",
                // HH:MM next to each date — saved with dt precision so the
                // day-scale timeline and hour drags keep the exact times.
                time_start: (t.dt_start || "").slice(11, 16) || "09:00",
                time_stop: (t.dt_stop || "").slice(11, 16) || "18:00",
                // duration_days counts inclusive days — a bar covering N day
                // cells is an N-day task (BRD-25 keeps it synced to
                // allocated_hours via hours_per_day).
                duration_days: t.date_start && t.date_stop
                    ? dayDiff(parseDay(t.date_start), parseDay(t.date_stop)) + 1
                    : 0,
                // The inspector edits duration in hours (allocated_hours);
                // the Start/Finish window stays a separate, explicit input.
                allocated_hours: t.allocated_hours,
                progress: t.progress,
                user_id: (t.user_ids && t.user_ids[0]) || false,
                depend_on_ids: [...(t.depend_on_ids || [])],
                dependent_ids: [...(t.dependent_ids || [])],
                addPredecessorId: "",
                addSuccessorId: "",
            };
        } catch (error) {
            this.notification.add(error.data?.message || _t("The task could not be loaded."), { type: "danger" });
            this.state.inspectorOpen = false;
        } finally {
            this.state.inspectorLoading = false;
        }
    }

    closeInspector() {
        this.state.inspectorOpen = false;
        this.state.draftParentId = null;
    }

    // ---- Baseline vs Current ----------------------------------------------

    formatDay(str) {
        if (!str) {
            return "—";
        }
        // Compact "7 Eyl" — the narrow inspector columns can't afford the
        // weekday name.
        return getCalendarFormats().dayMonth.format(parseDay(str));
    }

    formatDayVariance(days) {
        if (days === false || days === null || days === undefined || Number.isNaN(days)) {
            return "—";
        }
        if (days > 0) {
            return `+${days}d`;
        }
        if (days < 0) {
            return `−${Math.abs(days)}d`;
        }
        return "0d";
    }

    formatHoursCount(hours) {
        if (hours === false || hours === null || hours === undefined || Number.isNaN(hours)) {
            return "—";
        }
        return `${Math.round(hours * 100) / 100}h`;
    }

    formatHoursVariance(hours) {
        if (hours === false || hours === null || hours === undefined || Number.isNaN(hours)) {
            return "—";
        }
        const abs = Math.round(Math.abs(hours) * 100) / 100;
        if (hours > 0) {
            return `+${abs}h`;
        }
        if (hours < 0) {
            return `−${abs}h`;
        }
        return "0h";
    }

    // A positive schedule variance means a delay: highlight it; a negative one
    // means the task moved earlier or got shorter.
    varianceClass(days) {
        if (days > 0) {
            return "o_cp_planner_var_delay";
        }
        if (days < 0) {
            return "o_cp_planner_var_gain";
        }
        return "text-muted";
    }

    get baselineStartVariance() {
        const { form, baseline } = this.state;
        if (!form?.date_start || !baseline?.date_start) {
            return false;
        }
        return dayDiff(parseDay(baseline.date_start), parseDay(form.date_start));
    }

    get baselineStopVariance() {
        const { form, baseline } = this.state;
        if (!form?.date_stop || !baseline?.date_stop) {
            return false;
        }
        return dayDiff(parseDay(baseline.date_stop), parseDay(form.date_stop));
    }

    get baselineDurationVariance() {
        const { form, baseline } = this.state;
        if (form?.allocated_hours === undefined || baseline?.allocated_hours === false || baseline?.allocated_hours === undefined) {
            return false;
        }
        return form.allocated_hours - baseline.allocated_hours;
    }

    formatHours(hours) {
        if (hours === false || hours === null || hours === undefined) {
            return "—";
        }
        const sign = hours > 0 ? "+" : hours < 0 ? "−" : "";
        const abs = Math.abs(hours);
        return `${sign}${Math.round(abs * 10) / 10}h`;
    }

    get impactStatusLabel() {
        const labels = {
            critical_impact: _t("Critical Impact"),
            within_slack: _t("Within Slack"),
            duration_reduced: _t("Duration Reduced"),
            no_impact: _t("No Impact"),
        };
        return labels[this.state.impact?.delay_impact_status] || "—";
    }

    async openBaselineHistory() {
        if (!this.state.projectId) {
            return;
        }
        try {
            const action = await this.orm.call(
                "project.project", "action_view_critical_path_baselines", [this.state.projectId],
            );
            this.action.doAction(action);
        } catch (error) {
            this.notification.add(error.data?.message || _t("Baseline history could not be opened."), { type: "danger" });
        }
    }

    // ---- Quick Inspector form handlers ------------------------------------

    onStartChange(ev) {
        const form = this.state.form;
        form.date_start = ev.target.value;
        if (form.date_start) {
            form.date_stop = isoDay(addDays(
                parseDay(form.date_start), Math.max((form.duration_days || 1) - 1, 0),
            ));
        }
    }

    onStopChange(ev) {
        const form = this.state.form;
        form.date_stop = ev.target.value;
        if (form.date_stop && form.date_start) {
            form.duration_days = Math.max(
                dayDiff(parseDay(form.date_start), parseDay(form.date_stop)) + 1, 0,
            );
        }
    }

    onDurationChange(ev) {
        const form = this.state.form;
        form.allocated_hours = Math.max(Number(ev.target.value) || 0, 0);
    }

    taskLabel(id) {
        const task = this.taskById.get(id);
        return task ? `${task.wbs_code} ${task.name}`.trim() : `#${id}`;
    }

    addPredecessor(ev) {
        const form = this.state.form;
        const id = Number(ev.target.value);
        if (id && !form.depend_on_ids.includes(id)) {
            form.depend_on_ids.push(id);
        }
        form.addPredecessorId = "";
    }

    removePredecessor(id) {
        const form = this.state.form;
        form.depend_on_ids = form.depend_on_ids.filter((depId) => depId !== id);
    }

    addSuccessor(ev) {
        const form = this.state.form;
        const id = Number(ev.target.value);
        if (id && !form.dependent_ids.includes(id)) {
            form.dependent_ids.push(id);
        }
        form.addSuccessorId = "";
    }

    removeSuccessor(id) {
        const form = this.state.form;
        form.dependent_ids = form.dependent_ids.filter((depId) => depId !== id);
    }

    // ---- Dependency edge editor (BRD Dependency Lag) ---------------------

    // Edge attributes of (predId → taskId) from the planner payload.
    depEdge(taskId, predId) {
        const task = this.taskById.get(taskId);
        return (task?.dependencies || []).find((dep) => dep.task_id === predId) || null;
    }

    // Suffix shown on the Inspector predecessor chips — "FS", "SS +2d".
    depChipText(predId) {
        const edge = this.depEdge(this.state.inspector?.id, predId);
        if (!edge) {
            return "";
        }
        const parts = [(edge.type || "fs").toUpperCase()];
        if (edge.lag) {
            parts.push(
                `${edge.lag > 0 ? "+" : ""}${edge.lag}${edge.unit === "days" ? "d" : "h"}`,
            );
        }
        return `· ${parts.join(" ")}`;
    }

    openDepEditor(taskId, predId, ev) {
        ev.stopPropagation();
        const edge = this.depEdge(taskId, predId);
        this.state.depEdit = {
            taskId,
            predId,
            type: edge?.type || "fs",
            lag: edge?.lag || 0,
            unit: edge?.unit || "hours",
            x: ev.clientX,
            y: ev.clientY,
        };
    }

    closeDepEdit() {
        this.state.depEdit = null;
    }

    async saveDepEdit() {
        const edit = this.state.depEdit;
        if (!edit) {
            return;
        }
        try {
            await this.orm.call("project.task", "update_planner_dependency", [edit.taskId], {
                depends_on_id: edit.predId,
                relationship_type: edit.type,
                lag: Number(edit.lag) || 0,
                lag_unit: edit.unit,
            });
            this.state.depEdit = null;
            const collapsed = this.state.collapsedIds;
            await this.loadProject(this.state.projectId);
            this.state.collapsedIds = collapsed;
            if (this.state.inspectorOpen && this.state.inspector?.id) {
                await this.loadInspector(this.state.inspector.id);
            }
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The dependency could not be saved."),
                { type: "danger" },
            );
        }
    }

    async saveInspector() {
        const form = this.state.form;
        const isDraft = !!this.state.draftParentId && !this.state.inspector?.id;
        const taskId = this.state.inspector?.id;
        if ((!taskId && !isDraft) || !form) {
            return;
        }
        this.state.saving = true;
        try {
            const name = form.name?.trim() || _t("New Subtask");
            let savedId = taskId;
            if (isDraft) {
                // Draft subtask: create the record only now, then run the
                // same update path so dates/assignee/dependencies get the
                // standard planner conversion.
                const ids = await this.orm.create("project.task", [{
                    name: name,
                    project_id: this.state.projectId,
                    parent_id: this.state.draftParentId,
                }]);
                savedId = ids[0];
                this.state.draftParentId = null;
            }
            // Unchanged date+time fields stay out of the write — a
            // duration-only edit must reach the server without an explicit
            // finish so it can stretch date_deadline and reschedule the
            // successor chain (BRD Auto-Scheduling).
            const inspector = this.state.inspector || {};
            const startChanged = isDraft
                || (form.date_start || "") !== (inspector.date_start || "")
                || (form.time_start || "09:00")
                    !== ((inspector.dt_start || "").slice(11, 16) || "09:00");
            const stopChanged = isDraft
                || (form.date_stop || "") !== (inspector.date_stop || "")
                || (form.time_stop || "18:00")
                    !== ((inspector.dt_stop || "").slice(11, 16) || "18:00");
            await this.orm.call("project.task", "update_planner_task", [savedId], {
                values: {
                    name: name,
                    ...(startChanged ? {
                        date_start: form.date_start || false,
                        dt_start: form.date_start
                            ? `${form.date_start} ${form.time_start || "09:00"}`
                            : false,
                    } : {}),
                    ...(stopChanged ? {
                        date_stop: form.date_stop || false,
                        // Time-of-day input — written with dt precision so
                        // the day-scale timeline shows the exact clock time.
                        dt_stop: form.date_stop
                            ? `${form.date_stop} ${form.time_stop || "18:00"}`
                            : false,
                    } : {}),
                    duration_days: form.duration_days,
                    allocated_hours: form.allocated_hours,
                    progress: form.progress || 0,
                    user_ids: form.user_id ? [form.user_id] : [],
                    depend_on_ids: form.depend_on_ids,
                    dependent_ids: form.dependent_ids,
                },
            });
            const collapsed = this.state.collapsedIds;
            await this.loadProject(this.state.projectId);
            this.state.collapsedIds = collapsed;
            this.state.selectedId = savedId;
            await this.loadInspector(savedId);
        } catch (error) {
            this.notification.add(error.data?.message || _t("The task could not be saved."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    openInspectorTask() {
        if (this.state.inspector?.id) {
            this.openTask({ id: this.state.inspector.id });
        }
    }

    // BRD (quick subtask creation): the small "+" next to each WBS row
    // name opens the Quick Inspector as an unsaved draft for a child of
    // that row. No record is created until the user presses Save —
    // closing the Inspector without saving leaves nothing behind.
    async quickAddSubtask(task, ev) {
        ev.stopPropagation();
        try {
            // Reuse the parent's detail call to populate state.options
            // (the assignee select) — no record is created here.
            const detail = await this.orm.call("project.task", "get_planner_detail", [task.id]);
            this.state.selectedId = 0;
            this.state.inspector = null;
            this.state.inspectorOpen = true;
            this.state.inspectorLoading = false;
            this.state.draftParentId = task.id;
            this.state.baseline = null;
            this.state.impact = null;
            this.state.options = detail.options;
            this.state.depOpen = false;
            const start = task.date_start || "";
            const stop = task.date_stop || "";
            this.state.form = {
                name: "",
                date_start: start,
                date_stop: stop,
                time_start: (task.dt_start || "").slice(11, 16) || "09:00",
                time_stop: (task.dt_stop || "").slice(11, 16) || "18:00",
                duration_days: start && stop ? dayDiff(parseDay(start), parseDay(stop)) + 1 : 0,
                allocated_hours: 0,
                progress: 0,
                user_id: false,
                depend_on_ids: [],
                dependent_ids: [],
                addPredecessorId: "",
                addSuccessorId: "",
            };
        } catch (error) {
            this.notification.add(error.data?.message || _t("The subtask could not be created."), {
                type: "danger",
            });
        }
    }

    openTask(task) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: task.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // Execution info rendered right after the bar. Which values appear is
    // chosen per project via the Bar Info panel (BRD-17), max BAR_INFO_MAX.
    barInfoStyle(task) {
        const bar = this.barGeometry(task);
        if (!bar) {
            return "display:none";
        }
        return `left:${bar.left + bar.width + 8}px`;
    }

    barInfoValue(task, key) {
        const hours = (v) => `${Math.round((v || 0) * 100) / 100}h`;
        switch (key) {
            case "name":
                return task.name || "";
            case "allocated_hours":
                return hours(task.allocated_hours);
            case "effective_hours":
                return hours(task.effective_hours);
            case "progress":
                // progress arrives as a 0..1 ratio, capped at 100% for display
                return getCalendarFormats().percent.format(Math.min(task.progress || 0, 1));
            case "date_start":
                return task.date_start ? dayLabel(parseDay(task.date_start)) : "";
            case "date_stop":
                return task.date_stop ? dayLabel(parseDay(task.date_stop)) : "";
            default:
                return "";
        }
    }

    barInfoText(task) {
        return this.state.barInfoKeys
            .map((key) => this.barInfoValue(task, key))
            .filter(Boolean)
            .join(" • ");
    }

    // The selected keys live in a {projectId: {keys, slack}} map so each
    // project keeps its own bar labels across reloads. Older entries stored
    // a bare array of keys — they still load, with slack defaulting to on.
    loadBarInfoKeys() {
        try {
            const all = JSON.parse(localStorage.getItem(BAR_INFO_STORE_KEY) || "{}");
            const saved = all[this.state.projectId];
            const keys = Array.isArray(saved) ? saved : saved?.keys;
            if (Array.isArray(keys)) {
                const valid = new Set(BAR_INFO_FIELDS.map((f) => f.key));
                this.state.barInfoKeys = keys.filter((k) => valid.has(k)).slice(0, BAR_INFO_MAX);
                this.state.slackVisible = saved.slack !== false;
                return;
            }
        } catch {
            // corrupted storage — fall through to the defaults
        }
        this.state.barInfoKeys = [...BAR_INFO_DEFAULT];
        this.state.slackVisible = true;
    }

    persistBarInfoKeys() {
        let all = {};
        try {
            all = JSON.parse(localStorage.getItem(BAR_INFO_STORE_KEY) || "{}");
        } catch {
            // corrupted storage — start over
        }
        all[this.state.projectId] = {
            keys: this.state.barInfoKeys,
            slack: this.state.slackVisible,
        };
        try {
            localStorage.setItem(BAR_INFO_STORE_KEY, JSON.stringify(all));
        } catch {
            // storage unavailable — the choice just will not persist
        }
    }

    toggleBarInfoField(key) {
        const keys = [...this.state.barInfoKeys];
        const idx = keys.indexOf(key);
        if (idx >= 0) {
            keys.splice(idx, 1);
        } else if (keys.length >= BAR_INFO_MAX) {
            this.notification.add(_t("You can select up to 3 fields."), { type: "warning" });
            return;
        } else {
            keys.push(key);
        }
        this.state.barInfoKeys = keys;
        this.persistBarInfoKeys();
    }

    // ---- Slack (total float) label left of the bar (BRD-18) -----------------
    // The value comes straight from the stored critical-path calculation
    // (LS - ES in allocated-hours); nothing is recomputed client-side.

    toggleSlackLabel() {
        this.state.slackVisible = !this.state.slackVisible;
        this.persistBarInfoKeys();
    }

    slackText(task) {
        if (task.is_critical) {
            return "CP";
        }
        const slack = Math.round((task.critical_slack || 0) * 10) / 10;
        return `+${slack}h`;
    }

    // Approximate width of the lead-in cluster (slack chip + ! + ✓) so
    // dependency arrows can end left of it instead of overlapping the icons.
    barLeadWidth(task) {
        let w = 0;
        if (this.state.slackVisible) {
            w += 8 + this.slackText(task).length * 5;
        }
        if (this.isOverdue(task)) {
            w += (w ? 4 : 0) + 11;
        }
        if (task.is_done) {
            w += (w ? 4 : 0) + 10;
        }
        return w ? w + 4 : 0; // + the 4px anchor gap in barLeadStyle
    }

    // Right edge of the lead-in cluster anchored just before the bar —
    // translateX(-100%) keeps it outside the bar without measuring widths.
    barLeadStyle(task) {
        const bar = this.barGeometry(task);
        if (!bar) {
            return "display:none";
        }
        return `left:${bar.left - 4}px;transform:translateX(-100%)`;
    }

    // ---- Task bar drag & resize -------------------------------------------

    onBarPointerDown(task, mode, ev) {
        if (!task.date_start || !task.date_stop || task.is_done || ev.button !== 0) {
            return;
        }
        if (this.state.canEdit === false) {
            this.notification.add(
                _t("You do not have permission to edit tasks in this project."),
                { type: "warning" },
            );
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.dragging = {
            task,
            mode,
            startX: ev.clientX,
            extraDx: 0, // px added by edge auto-scroll — keeps dx in sync
            moved: false,
        };
        this._lastDragX = ev.clientX;
        this._dragScrollTimer = setInterval(() => this.tickDragAutoScroll(), 30);
        const onMove = (e) => this.onDragMove(e);
        const onUp = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            window.removeEventListener("pointercancel", onUp);
            clearInterval(this._dragScrollTimer);
            this._dragScrollTimer = null;
            this._lastDragX = null;
            this.onDragEnd();
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onUp);
    }

    // While a bar is held near either timeline edge the view scrolls on
    // its own; extraDx compensates the scrolled px so the drag delta
    // keeps tracking the pointer, and the range grows ahead of the bar.
    tickDragAutoScroll() {
        const el = this.ganttScrollRef.el;
        const dragging = this.dragging;
        if (!el || !dragging || this._lastDragX == null) {
            return;
        }
        const rect = el.getBoundingClientRect();
        const margin = 64;
        let delta = 0;
        if (this._lastDragX > rect.right - margin) {
            delta = Math.min(4 + (this._lastDragX - (rect.right - margin)) * 0.25, 24);
        } else if (this._lastDragX < rect.left + margin) {
            delta = -Math.min(4 + (rect.left + margin - this._lastDragX) * 0.25, 24);
        }
        if (delta) {
            const before = el.scrollLeft;
            el.scrollLeft += delta;
            // Only count the scroll that actually happened — at the track
            // end (before the range extension renders) the bar must wait
            // rather than run ahead of the viewport.
            dragging.extraDx += el.scrollLeft - before;
            this.applyDragDelta(this._lastDragX - dragging.startX + dragging.extraDx);
        }
        const drag = this.state.drag;
        if (drag) {
            if (parseDay(drag.stop) >= addDays(this.plannerRange.end, -3)) {
                this.extendRange("right");
            } else if (parseDay(drag.start) <= addDays(this.plannerRange.start, 3)) {
                this.extendRange("left");
            }
        }
    }

    onDragMove(ev) {
        const dragging = this.dragging;
        if (!dragging) {
            return;
        }
        this._lastDragX = ev.clientX;
        this.applyDragDelta(ev.clientX - dragging.startX + (dragging.extraDx || 0));
    }

    applyDragDelta(dx) {
        const dragging = this.dragging;
        if (!dragging) {
            return;
        }
        if (!dragging.moved && Math.abs(dx) < 4) {
            return; // click threshold — avoids accidental micro-drags
        }
        dragging.moved = true;
        const task = dragging.task;
        const rowIdx = this.visibleTasks.findIndex((row) => row.id === task.id);
        if (this.state.scale === "day") {
            // Day scale drags at hour precision — one column = one hour.
            const deltaH = Math.round(dx / (this.state.pxPerDay / 24));
            const baseStart = task.dt_start
                ? parseDt(task.dt_start)
                : new Date(parseDay(task.date_start).getTime() + 9 * 3600000);
            const baseStop = task.dt_stop
                ? parseDt(task.dt_stop)
                : new Date(parseDay(task.date_stop).getTime() + 18 * 3600000);
            let startDt = baseStart;
            let stopDt = baseStop;
            if (dragging.mode === "move") {
                startDt = new Date(baseStart.getTime() + deltaH * 3600000);
                stopDt = new Date(baseStop.getTime() + deltaH * 3600000);
            } else if (dragging.mode === "left") {
                startDt = new Date(baseStart.getTime() + deltaH * 3600000);
                if (startDt >= stopDt) {
                    startDt = new Date(stopDt.getTime() - 3600000);
                }
            } else {
                stopDt = new Date(baseStop.getTime() + deltaH * 3600000);
                if (stopDt <= startDt) {
                    stopDt = new Date(startDt.getTime() + 3600000);
                }
            }
            this.state.drag = {
                taskId: task.id,
                rowIdx,
                start: isoDay(startDt),
                stop: isoDay(stopDt),
                dtStart: fmtDt(startDt),
                dtStop: fmtDt(stopDt),
            };
            return;
        }
        const delta = Math.round(dx / this.state.pxPerDay);
        let start = parseDay(task.date_start);
        let stop = parseDay(task.date_stop);
        if (dragging.mode === "move") {
            start = addDays(start, delta);
            stop = addDays(stop, delta);
        } else if (dragging.mode === "left") {
            start = addDays(start, delta);
            if (start > stop) {
                start = stop;
            }
        } else {
            stop = addDays(stop, delta);
            if (stop < start) {
                stop = start;
            }
        }
        this.state.drag = {
            taskId: task.id,
            rowIdx,
            start: isoDay(start),
            stop: isoDay(stop),
        };
    }

    onDragEnd() {
        const dragging = this.dragging;
        const drag = this.state.drag;
        this.dragging = null;
        this.state.drag = null;
        if (!dragging?.moved || !drag) {
            return;
        }
        // Swallow the click that follows pointerup so a drag does not also
        // re-open the inspector mid-write; a real next click clears it anyway.
        this.suppressClick = true;
        setTimeout(() => {
            this.suppressClick = false;
        }, 0);
        this.persistTaskDates(dragging.task, drag);
    }

    async persistTaskDates(task, drag) {
        // Hour-precision drags (day scale) persist dt_start/dt_stop; other
        // scales keep the day-string + duration_days path unchanged.
        const values = drag.dtStart && drag.dtStop
            ? { dt_start: drag.dtStart, dt_stop: drag.dtStop }
            : {
                date_start: drag.start,
                date_stop: drag.stop,
                duration_days: dayDiff(parseDay(drag.start), parseDay(drag.stop)) + 1,
            };
        try {
            await this.orm.call("project.task", "update_planner_task", [task.id], { values });
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The task dates could not be saved."), { type: "danger" },
            );
            return;
        }
        await this.reloadPlannerData();
        if (this.state.inspectorOpen && this.state.inspector?.id === task.id) {
            await this.loadInspector(task.id);
        }
    }

    // Reload tasks while keeping selection/collapse/inspector state — used by
    // bar drags and by the baseline-compare switch in the history panel.
    async reloadPlannerData() {
        const collapsed = this.state.collapsedIds;
        const selectedId = this.state.selectedId;
        const inspectorOpen = this.state.inspectorOpen;
        await this.loadProject(this.state.projectId);
        this.state.collapsedIds = collapsed;
        this.state.selectedId = selectedId;
        this.state.inspectorOpen = inspectorOpen;
    }

    // ---- Baseline History panel -------------------------------------------

    async toggleHistory() {
        this.state.historyOpen = !this.state.historyOpen;
        if (this.state.historyOpen) {
            await this.loadBaselineHistory();
            return;
        }
        this.state.historyDetail = null;
        await this.clearBaselineCompare();
    }

    async loadBaselineHistory() {
        if (!this.state.projectId) {
            return;
        }
        this.state.historyLoading = true;
        try {
            this.state.historyList = await this.orm.call(
                "project.project", "get_planner_baseline_history", [this.state.projectId],
            );
        } catch (error) {
            this.state.historyList = [];
            this.notification.add(
                error.data?.message || _t("The baseline history could not be loaded."),
                { type: "danger" },
            );
        } finally {
            this.state.historyLoading = false;
        }
    }

    // Baseline Save — the user picks a predefined active title; the
    // version number keeps auto-incrementing server-side (v1.19 → v1.20).
    async openBaselineSave() {
        this.state.baselineSaveTitle = "";
        try {
            this.state.baselineTitles = await this.orm.searchRead(
                "project.baseline.title",
                [["active", "=", true]],
                ["name"],
                { order: "name" },
            );
        } catch {
            this.state.baselineTitles = [];
        }
        this.state.baselineSaveOpen = true;
    }

    cancelBaselineSave() {
        this.state.baselineSaveOpen = false;
        this.state.baselineSaveTitle = "";
    }

    async saveBaseline() {
        const label = (this.state.baselineSaveTitle || "").trim();
        if (!label) {
            this.notification.add(_t("Please select a baseline title."), { type: "warning" });
            return;
        }
        this.state.baselineSaving = true;
        try {
            await this.orm.call(
                "project.project", "action_create_critical_path_baseline",
                [this.state.projectId], { baseline_label: label },
            );
            this.cancelBaselineSave();
            await this.loadBaselineHistory();
            // The new baseline may shift delay-impact baselines — refresh.
            await this.reloadPlannerData();
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The baseline could not be created."),
                { type: "danger" },
            );
        } finally {
            this.state.baselineSaving = false;
        }
    }

    async selectBaselineVersion(item) {
        if (this.state.historyDetail?.id === item.id) {
            this.state.historyDetail = null;
            await this.clearBaselineCompare();
            return;
        }
        this.state.historyDetailLoading = true;
        try {
            this.state.historyDetail = await this.orm.call(
                "project.project", "get_planner_baseline_summary", [this.state.projectId],
                { baseline_id: item.id },
            );
            // Show this historical baseline as the Gantt reference layer.
            this.state.compareBaselineId = item.id;
            await this.reloadPlannerData();
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The baseline summary could not be loaded."),
                { type: "danger" },
            );
        } finally {
            this.state.historyDetailLoading = false;
        }
    }

    async clearBaselineCompare() {
        if (!this.state.compareBaselineId) {
            return;
        }
        this.state.compareBaselineId = null;
        await this.reloadPlannerData();
    }

    // History → changed task → Planner selection + Quick Inspector.
    async openHistoryTask(change) {
        const task = this.taskById.get(change.task_id);
        if (!task) {
            this.notification.add(
                _t("This task is no longer part of the current project plan."),
                { type: "warning" },
            );
            return;
        }
        // Expand collapsed ancestors so the row is actually visible.
        if (this.state.collapsedIds.size) {
            const ids = new Set(this.state.collapsedIds);
            let current = task;
            while (current && current.parent_id) {
                ids.delete(current.parent_id);
                current = this.taskById.get(current.parent_id);
            }
            this.state.collapsedIds = ids;
        }
        this.state.selectedId = task.id;
        this.state.inspectorOpen = true;
        await this.loadInspector(task.id);
        const idx = this.visibleTasks.findIndex((row) => row.id === task.id);
        const top = Math.max(idx * PLANNER_ROW_H - PLANNER_ROW_H * 2, 0);
        if (this.wbsRowsRef.el) {
            this.wbsRowsRef.el.scrollTop = top;
        }
        const scroll = this.ganttScrollRef.el;
        if (scroll) {
            scroll.scrollTop = top;
            const bar = this.barGeometry(task);
            if (bar) {
                scroll.scrollLeft = Math.max(bar.left - 120, 0);
            }
        }
    }

    formatHistoryDate(str) {
        if (!str) {
            return "";
        }
        const date = new Date(str.replace(" ", "T"));
        return getCalendarFormats().mediumDate.format(date);
    }

    formatSignedHours(hours) {
        const value = Math.round(hours * 100) / 100;
        return `${value > 0 ? "+" : ""}${value}h`;
    }

    formatMoney(value, symbol) {
        const formatted = getCalendarFormats().money.format(value || 0);
        return symbol ? `${formatted} ${symbol}` : formatted;
    }

    formatSignedMoney(value, symbol) {
        const formatted = getCalendarFormats().money.format(Math.abs(value || 0));
        const signed = `${(value || 0) > 0 ? "+" : (value || 0) < 0 ? "−" : ""}${formatted}`;
        return symbol ? `${signed} ${symbol}` : signed;
    }

    formatHours(hours) {
        return `${Math.round((hours || 0) * 100) / 100}h`;
    }

    // ---- Optional WBS date columns -----------------------------------------

    get wbsPanelWidth() {
        return 340 + (this.state.showStartCol ? 88 : 0) + (this.state.showFinishCol ? 88 : 0);
    }

    formatColDate(str) {
        if (!str) {
            return "–";
        }
        return getCalendarFormats().compactDate.format(parseDay(str));
    }

    // ---- Resource Planning workspace (BRD-21) ------------------------------
    // Requirements and assignments live in the existing resource models; the
    // Planner only serializes and mutates them through planner_* methods.
    // The workspace is a large modal — the Quick Inspector only links to it.

    async openResourceWorkspace(task, ev) {
        ev?.stopPropagation();
        this.state.selectedId = task.id;
        this.state.resTask = {
            id: task.id,
            name: task.name || "",
            wbs_code: task.wbs_code || "",
        };
        this.state.resModalOpen = true;
        this.state.resSelReqId = null;
        this.state.resSelOptKey = null;
        this.state.resOptions = [];
        this.state.resWindow = null;
        this.state.resRequired = null;
        this.state.resAddOpen = false;
        this.state.resEditingId = null;
        this.state.resTlAnchor = null;
        this.state.resTlDrag = null;
        this.state.resTlPending = null;
        this.state.resSelAssignId = null;
        this.state.resAssignEdit = null;
        this.state.resAssignDelConfirm = false;
        await this.loadResources();
    }

    closeResourceWorkspace() {
        this.state.resModalOpen = false;
    }

    async loadResources() {
        if (!this.state.resTask?.id) {
            return;
        }
        this.state.resLoading = true;
        try {
            this.state.resData = await this.orm.call(
                "project.task", "get_planner_resources", [this.state.resTask.id],
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("Resources could not be loaded."), { type: "danger" },
            );
            this.state.resData = { requirements: [], roles: [], task_dates: {} };
        } finally {
            this.state.resLoading = false;
        }
    }

    // Resource mutations change the row badges, the requirement list and the
    // candidates' availability, so all three refresh afterwards.
    async refreshResources() {
        const selReqId = this.state.resSelReqId;
        await this.loadResources();
        if (selReqId && this.resSelectedReq) {
            await this.loadResOptions(selReqId);
        } else {
            this.state.resSelReqId = null;
            this.state.resOptions = [];
        }
        await this.reloadPlannerData();
    }

    get resSelectedReq() {
        return (this.state.resData?.requirements || []).find(
            (req) => req.id === this.state.resSelReqId,
        ) || null;
    }

    async selectRequirement(req) {
        this.state.resTlAnchor = null;
        this.state.resTlDrag = null;
        this.state.resTlPending = null;
        this.state.resSelOptKey = null;
        this.state.resSelAssignId = null;
        this.state.resAssignEdit = null;
        this.state.resAssignDelConfirm = false;
        if (this.state.resSelReqId === req.id) {
            this.state.resSelReqId = null;
            this.state.resSelOptKey = null;
            this.state.resOptions = [];
            return;
        }
        this.state.resSelReqId = req.id;
        await this.loadResOptions(req.id);
    }

    async loadResOptions(reqId) {
        this.state.resOptionsLoading = true;
        this.state.resTlDrag = null;
        const range = this.resTlRange;
        try {
            const data = await this.orm.call(
                "project.task", "planner_get_assignment_options", [this.state.resTask.id],
                {
                    requirement_id: reqId,
                    window_start: range ? isoDay(range.start) : false,
                    window_end: range ? isoDay(addDays(range.end, -1)) : false,
                },
            );
            this.state.resOptions = data.options || [];
            this.state.resWindow = data.window || null;
            this.state.resRequired = data.required || null;
        } catch (error) {
            this.state.resOptions = [];
            this.notification.add(
                error.data?.message || _t("Resources could not be loaded."), { type: "danger" },
            );
        } finally {
            this.state.resOptionsLoading = false;
        }
    }

    openRequirementForm(req = null) {
        const dates = this.state.resData?.task_dates || {};
        this.state.resEditingId = req?.id || null;
        this.state.resForm = {
            role_id: req?.role_id || "",
            quantity: req?.quantity ?? 1,
            planned_hours: req?.planned_hours ?? 0,
            description: req?.description || "",
            date_start: req?.date_start || dates.date_start || "",
            date_end: req?.date_end || dates.date_stop || "",
        };
        this.state.resAddOpen = true;
    }

    async saveRequirement() {
        const form = this.state.resForm;
        if (!form?.role_id) {
            this.notification.add(_t("Select a resource role first."), { type: "warning" });
            return;
        }
        if (this.state.resData?.rate_template && this.resFormRate() === null) {
            this.notification.add(
                _t("No hourly rate for this role in the project rate templates."),
                { type: "warning" },
            );
            return;
        }
        try {
            await this.orm.call(
                "project.task", "planner_save_requirement", [this.state.resTask.id],
                {
                    values: {
                        id: this.state.resEditingId || false,
                        role_id: parseInt(form.role_id, 10),
                        quantity: parseFloat(form.quantity) || 1,
                        planned_hours: parseFloat(form.planned_hours) || 0,
                        description: form.description || "",
                        date_start: form.date_start || false,
                        date_end: form.date_end || false,
                    },
                },
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The requirement could not be saved."), { type: "danger" },
            );
            return;
        }
        this.state.resAddOpen = false;
        this.state.resEditingId = null;
        await this.refreshResources();
    }

    async deleteRequirement(req) {
        try {
            await this.orm.call(
                "project.task", "planner_delete_requirement", [this.state.resTask.id],
                { requirement_id: req.id },
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The requirement could not be removed."), { type: "danger" },
            );
            return;
        }
        await this.refreshResources();
    }

    resCandidateKey(opt) {
        return opt.employee_id ? `e${opt.employee_id}` : `q${opt.equipment_id}`;
    }

    resStars(opt) {
        return Array.from({ length: opt.priority || 0 }, (_, i) => i);
    }

    resAvatarUrl(opt) {
        return opt.employee_id ? `/web/image/hr.employee/${opt.employee_id}/avatar_128` : "";
    }

    get resSelectedOption() {
        return this.state.resOptions.find(
            (opt) => this.resCandidateKey(opt) === this.state.resSelOptKey,
        ) || null;
    }

    // Selecting a candidate never assigns; a pending preview simply moves to
    // the newly selected resource (BRD-23 §11/§12).
    async selectCandidate(opt) {
        const key = this.resCandidateKey(opt);
        this.state.resSelOptKey = this.state.resSelOptKey === key ? null : key;
        this.state.resSelAssignId = null;
        this.state.resAssignEdit = null;
        this.state.resAssignDelConfirm = false;
        const pend = this.state.resTlPending;
        if (pend) {
            pend.conflict = this.resTlConflict(pend.startMs, pend.endMs);
            await this.updateResTlPendingEst();
        }
    }

    async assignResource(opt, startDt, endDt) {
        const req = this.resSelectedReq;
        if (!req) {
            return false;
        }
        try {
            await this.orm.call(
                "project.task", "planner_assign_resource", [this.state.resTask.id],
                {
                    requirement_id: req.id,
                    employee_id: opt.employee_id || false,
                    equipment_id: opt.equipment_id || false,
                    date_start: startDt || false,
                    date_end: endDt || false,
                },
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The resource could not be assigned."), { type: "danger" },
            );
            return false;
        }
        await this.refreshResources();
        return true;
    }

    async unassignResource(assignmentId) {
        try {
            await this.orm.call(
                "project.task", "planner_unassign_resource", [this.state.resTask.id],
                { assignment_id: assignmentId },
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The assignment could not be removed."), { type: "danger" },
            );
            return;
        }
        await this.refreshResources();
    }

    // Compact summary shown in the Inspector and next to the Manage button.
    resSummaryText(taskId) {
        const res = this.taskById.get(taskId)?.resources;
        if (!res || (!res.human && !res.equipment)) {
            return _t("No resource requirements yet");
        }
        const parts = [];
        if (res.human) {
            parts.push(`${res.human} × person`);
        }
        if (res.equipment) {
            parts.push(`${res.equipment} × equipment`);
        }
        if (res.open) {
            parts.push(_t("unassigned requirements"));
        }
        return parts.join(" · ");
    }

    resStatusLabel(req) {
        return {
            waiting: _t("Pending"),
            partial: _t("Partial"),
            assigned: _t("Assigned"),
        }[req.status] || "—";
    }

    resStatusClass(req) {
        return {
            waiting: "text-bg-danger",
            partial: "text-bg-warning",
            assigned: "text-bg-success",
        }[req.status] || "text-bg-secondary";
    }

    resAvailabilityLabel(opt) {
        return {
            fully_available: _t("Fully available"),
            partially_available: _t("Partially occupied"),
            unavailable: _t("Conflict"),
        }[opt.availability] || "—";
    }

    resAvailabilityDot(opt) {
        return {
            fully_available: "o_cp_res_dot_ok",
            partially_available: "o_cp_res_dot_warn",
            unavailable: "o_cp_res_dot_conflict",
        }[opt.availability] || "";
    }

    // ---- Candidate timeline (BRD-22) ---------------------------------------
    // Same scale semantics as the Resource Board: day = 24 hour columns,
    // week = 7 day columns, month = the anchor's calendar month. Anchored
    // on the requirement by default and shifted by ‹ › navigation.

    resTlUnitMs() {
        return { day: 3600000, week: DAY_MS, month: DAY_MS }[this.state.resTlScale];
    }

    get resTlRange() {
        const req = this.resSelectedReq;
        if (!req?.date_start || !req?.date_end) {
            return false;
        }
        const anchor = this.state.resTlAnchor || parseDay(req.date_start);
        if (this.state.resTlScale === "day") {
            return { start: anchor, end: addDays(anchor, 1) };
        }
        if (this.state.resTlScale === "month") {
            const start = startOfMonth(anchor);
            return {
                start,
                end: startOfMonth(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1)),
            };
        }
        const start = startOfWeek(anchor);
        return { start, end: addDays(start, 7) };
    }

    get resTlColumns() {
        const range = this.resTlRange;
        if (!range) {
            return [];
        }
        const cols = [];
        const unit = this.resTlUnitMs();
        for (let t = range.start.getTime(); t < range.end.getTime(); t += unit) {
            const d = new Date(t);
            if (this.state.resTlScale === "day") {
                cols.push({ label: pad2(d.getHours()) });
            } else {
                cols.push({
                    label: this.state.resTlScale === "month"
                        ? String(d.getDate())
                        : `${getCalendarFormats().weekdayShort.format(d)} ${pad2(d.getDate())}`,
                });
            }
        }
        return cols;
    }

    // Same caption row as the board: day name, month + ISO week, or month.
    get resTlCaption() {
        const range = this.resTlRange;
        if (!range) {
            return "";
        }
        const fmt = getCalendarFormats();
        if (this.state.resTlScale === "month") {
            return fmt.monthYear.format(range.start);
        }
        if (this.state.resTlScale === "week") {
            return `${fmt.monthYear.format(range.start)} · ${_t("Week")} ${isoWeek(range.start)}`;
        }
        return fmt.dayCaption.format(range.start);
    }

    async resTlNavigate(dir) {
        const range = this.resTlRange;
        if (!range) {
            return;
        }
        if (this.state.resTlScale === "month") {
            this.state.resTlAnchor = new Date(
                range.start.getFullYear(), range.start.getMonth() + dir, 1
            );
        } else {
            const step = this.state.resTlScale === "week" ? 7 * DAY_MS : DAY_MS;
            this.state.resTlAnchor = new Date(range.start.getTime() + dir * step);
        }
        await this.loadResOptions(this.state.resSelReqId);
    }

    async resTlToday() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        this.state.resTlAnchor = this.state.resTlScale === "month" ? startOfMonth(today)
            : this.state.resTlScale === "week" ? startOfWeek(today) : today;
        await this.loadResOptions(this.state.resSelReqId);
    }

    // Scale switching keeps the visible period: the anchor is derived from
    // the range shown under the previous scale instead of resetting to the
    // requirement (BRD-23 §2/§3).
    async setResTlScale(scale) {
        if (this.state.resTlScale === scale) {
            return;
        }
        const range = this.resTlRange;
        const cur = range ? range.start : new Date();
        this.state.resTlScale = scale;
        this.state.resTlAnchor = scale === "month" ? startOfMonth(cur)
            : scale === "week" ? startOfWeek(cur)
            : new Date(cur.getFullYear(), cur.getMonth(), cur.getDate());
        await this.loadResOptions(this.state.resSelReqId);
    }

    get resTlPickerValue() {
        const range = this.resTlRange;
        return range ? isoDay(range.start) : "";
    }

    // Direct date jump: day view opens that day, week its week, month its
    // month — same anchoring rules as the board picker.
    async onResTlDatePick(ev) {
        const val = ev.target.value;
        if (!val) {
            return;
        }
        const picked = parseDay(val);
        this.state.resTlAnchor = this.state.resTlScale === "month" ? startOfMonth(picked)
            : this.state.resTlScale === "week" ? startOfWeek(picked) : picked;
        await this.loadResOptions(this.state.resSelReqId);
    }

    resTlItemMs(item) {
        return {
            s: item.dt_start ? parseDt(item.dt_start).getTime()
                : parseDay(item.date_start).getTime() + 9 * 3600000,
            e: item.dt_end ? parseDt(item.dt_end).getTime()
                : parseDay(item.date_end).getTime() + 18 * 3600000,
        };
    }

    resTlMsToStyle(s, e) {
        const range = this.resTlRange;
        if (!range) {
            return "display:none";
        }
        const span = range.end.getTime() - range.start.getTime();
        const left = Math.max((s - range.start.getTime()) / span * 100, 0);
        const width = Math.min((e - s) / span * 100, 100 - left);
        return `left:${left}%;width:${Math.max(width, 1)}%`;
    }

    resTlItemStyle(item) {
        const drag = this.state.resTlDrag;
        if (drag && drag.itemId === item.id) {
            return this.resTlMsToStyle(drag.startMs, drag.endMs);
        }
        const { s, e } = this.resTlItemMs(item);
        return this.resTlMsToStyle(s, e);
    }

    resTlItemClass(item) {
        return {
            mine: item.mine,
            conflict: item.overlaps && !item.mine,
            dragging: this.state.resTlDrag?.itemId === item.id,
        };
    }

    // No candidate selected → one overview row per candidate resource so
    // workloads can be compared; selected → one focused row per booking.
    get resTlRows() {
        const selected = this.resSelectedOption;
        if (selected) {
            return (selected.schedule || []).map((item) => ({
                key: item.id, label: item.task_name, title: item.task_name, items: [item],
            }));
        }
        return this.state.resOptions.map((opt) => ({
            key: this.resCandidateKey(opt), label: opt.name, title: opt.name,
            items: opt.schedule || [], opt,
        }));
    }

    resTlRangeStyle() {
        const req = this.state.resRequired;
        if (!req?.start || !req?.end) {
            return "display:none";
        }
        const s = req.start_dt ? parseDt(req.start_dt).getTime()
            : parseDay(req.start).getTime() + 9 * 3600000;
        const e = req.end_dt ? parseDt(req.end_dt).getTime()
            : parseDay(req.end).getTime() + 18 * 3600000;
        return this.resTlMsToStyle(s, e);
    }

    resTlDragStyle() {
        const drag = this.state.resTlDrag;
        if (!drag) {
            return "display:none";
        }
        return this.resTlMsToStyle(drag.startMs, drag.endMs);
    }

    resTlDragClass() {
        const drag = this.state.resTlDrag;
        return {
            conflict: drag?.conflict,
            outside: drag?.outside,
        };
    }

    resTlDragText() {
        const drag = this.state.resTlDrag;
        if (!drag) {
            return "";
        }
        const s = new Date(drag.startMs);
        const e = new Date(drag.endMs);
        const sameDay = isoDay(s) === isoDay(e);
        const fmt = (d) => `${dayLabel(d)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
        return sameDay
            ? `${dayLabel(s)} ${pad2(s.getHours())}:${pad2(s.getMinutes())} – ${pad2(e.getHours())}:${pad2(e.getMinutes())}`
            : `${fmt(s)} → ${fmt(e)}`;
    }

    // ---- Pending assignment (BRD-23) ---------------------------------------
    // A released drag only becomes a preview; the server write waits for the
    // explicit "Assign" click. The preview itself stays draggable/resizable and
    // follows whichever candidate is selected.

    resTlPendingStyle() {
        const pend = this.state.resTlPending;
        if (!pend) {
            return "display:none";
        }
        return this.resTlMsToStyle(pend.startMs, pend.endMs);
    }

    resTlPendingClass() {
        const pend = this.state.resTlPending;
        return {
            conflict: pend?.conflict,
            outside: pend?.outside,
        };
    }

    resTlPendingText() {
        const pend = this.state.resTlPending;
        if (!pend) {
            return "";
        }
        const s = new Date(pend.startMs);
        const e = new Date(pend.endMs);
        const sameDay = isoDay(s) === isoDay(e);
        const fmt = (d) => `${dayLabel(d)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
        return sameDay
            ? `${dayLabel(s)} ${pad2(s.getHours())}:${pad2(s.getMinutes())} – ${pad2(e.getHours())}:${pad2(e.getMinutes())}`
            : `${fmt(s)} → ${fmt(e)}`;
    }

    resTlPendingDurationText() {
        const pend = this.state.resTlPending;
        if (!pend) {
            return "";
        }
        const hrs = pend.estHours ?? (pend.endMs - pend.startMs) / 3600000;
        return `${this.formatHours(hrs)} ${_t("planned")}`;
    }

    resTlPendingSet(s, e) {
        const pend = this.state.resTlPending;
        if (!pend) {
            return;
        }
        pend.startMs = Math.min(s, e);
        pend.endMs = Math.max(s, e);
        pend.conflict = this.resTlConflict(pend.startMs, pend.endMs);
        pend.outside = this.resTlOutside(pend.startMs, pend.endMs);
    }

    async updateResTlPendingEst() {
        const pend = this.state.resTlPending;
        const opt = this.resSelectedOption;
        const req = this.resSelectedReq;
        if (!pend || !opt || !req) {
            return;
        }
        try {
            pend.estHours = await this.orm.call(
                "project.task", "planner_estimate_assignment_hours",
                [this.state.resTask.id],
                {
                    requirement_id: req.id,
                    employee_id: opt.employee_id || false,
                    equipment_id: opt.equipment_id || false,
                    date_start: fmtDt(new Date(pend.startMs)),
                    date_end: fmtDt(new Date(pend.endMs)),
                },
            );
        } catch {
            pend.estHours = null;
        }
    }

    async confirmResTlPending() {
        const pend = this.state.resTlPending;
        const opt = this.resSelectedOption;
        if (!pend || !opt || pend.outside) {
            return;
        }
        const ok = await this.assignResource(
            opt, fmtDt(new Date(pend.startMs)), fmtDt(new Date(pend.endMs)),
        );
        if (ok) {
            this.state.resTlPending = null;
        }
    }

    cancelResTlPending() {
        this.state.resTlPending = null;
    }

    // ---- Existing assignment actions (BRD-24) ------------------------------
    // Clicking a bar selects it and opens the detail card; only assignments
    // of the selected requirement ("mine") can be edited or deleted — other
    // bars belong to different tasks/requirements and are view-only.

    selectResAssignment(item) {
        this.state.resSelAssignId =
            this.state.resSelAssignId === item.id ? null : item.id;
        this.state.resAssignEdit = null;
        this.state.resAssignDelConfirm = false;
    }

    get resSelectedAssignment() {
        const opt = this.resSelectedOption;
        if (!opt || !this.state.resSelAssignId) {
            return null;
        }
        return (opt.schedule || []).find(
            (item) => item.id === this.state.resSelAssignId
        ) || null;
    }

    resAssignTypeLabel() {
        const opt = this.resSelectedOption;
        if (!opt) {
            return "";
        }
        return opt.employee_id ? _t("Person") : _t("Equipment");
    }

    resAssignDurationText(item) {
        const hrs = item.planned_hours
            ?? (this.resTlItemMs(item).e - this.resTlItemMs(item).s) / 3600000;
        return `${this.formatHours(hrs)} ${_t("planned")}`;
    }

    // "Edit" reveals precise datetime inputs; move/resize on the bar
    // itself stays the primary interaction.
    openResAssignEdit() {
        const item = this.resSelectedAssignment;
        if (!item?.mine) {
            return;
        }
        this.state.resAssignEdit = {
            date_start: (item.dt_start || "").replace(" ", "T"),
            date_end: (item.dt_end || "").replace(" ", "T"),
        };
        this.state.resAssignDelConfirm = false;
    }

    cancelResAssignEdit() {
        this.state.resAssignEdit = null;
    }

    async saveResAssignEdit() {
        const item = this.resSelectedAssignment;
        const edit = this.state.resAssignEdit;
        if (!item || !edit?.date_start || !edit?.date_end) {
            return;
        }
        const start = new Date(edit.date_start);
        const end = new Date(edit.date_end);
        if (!(start < end)) {
            this.notification.add(
                _t("Start must be before finish — the assignment was not changed."),
                { type: "warning" },
            );
            this.state.resAssignEdit = null;
            return;
        }
        try {
            await this.orm.call(
                "project.task", "planner_update_assignment", [this.state.resTask.id],
                {
                    assignment_id: item.id,
                    date_start: fmtDt(start),
                    date_end: fmtDt(end),
                },
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The assignment could not be updated."),
                { type: "danger" },
            );
            return;
        }
        this.state.resAssignEdit = null;
        await this.refreshResources();
    }

    askDeleteResAssignment() {
        if (this.resSelectedAssignment?.mine) {
            this.state.resAssignDelConfirm = true;
            this.state.resAssignEdit = null;
        }
    }

    cancelDeleteResAssignment() {
        this.state.resAssignDelConfirm = false;
    }

    // Deletes only the assignment record — requirement, task and resource
    // master data are untouched; refresh updates status and availability.
    async confirmDeleteResAssignment() {
        const item = this.resSelectedAssignment;
        if (!item?.mine) {
            return;
        }
        this.state.resAssignDelConfirm = false;
        this.state.resSelAssignId = null;
        await this.unassignResource(item.id);
    }

    // ---- Timeline dragging -------------------------------------------------

    resTlPointMs(clientX, rect) {
        const range = this.resTlRange;
        const ratio = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
        return range.start.getTime() + ratio * (range.end.getTime() - range.start.getTime());
    }

    // Snap a timestamp to the scale unit: hour boundaries in the day view,
    // 09:00/18:00 day edges (the existing assignment defaults) in week and
    // month views.
    resTlSnap(ms, edge) {
        const d = new Date(ms);
        if (this.state.resTlScale === "day") {
            d.setMinutes(0, 0, 0);
            return edge === "end" ? d.getTime() + 3600000 : d.getTime();
        }
        d.setHours(edge === "end" ? 18 : 9, 0, 0, 0);
        return d.getTime();
    }

    resTlConflict(s, e, excludeId) {
        return (this.resSelectedOption?.schedule || []).some(
            (item) => item.id !== excludeId && this.resTlItemMs(item).s < e && this.resTlItemMs(item).e > s,
        );
    }

    resTlOutside(s, e) {
        const req = this.state.resRequired;
        if (!req?.start_dt || !req?.end_dt) {
            return false;
        }
        return s < parseDt(req.start_dt).getTime() || e > parseDt(req.end_dt).getTime();
    }

    resTlDragState(s, e) {
        const d = this.resTlDragging;
        return {
            mode: d.mode,
            itemId: d.item?.id,
            startMs: Math.min(s, e),
            endMs: Math.max(s, e),
            conflict: this.resTlConflict(Math.min(s, e), Math.max(s, e), d.item?.id),
            outside: this.resTlOutside(Math.min(s, e), Math.max(s, e)),
        };
    }

    onResTlTrackDown(ev) {
        // Empty track → drag creates a new assignment (bars handle their own
        // pointerdown; the required band does not block creation).
        if (
            ev.button !== 0 || !this.resSelectedOption
            || ev.target.closest(".o_cp_res_tl_bar, .o_cp_res_tl_new, .o_cp_res_tl_pending")
        ) {
            return;
        }
        ev.preventDefault();
        const rect = ev.currentTarget.getBoundingClientRect();
        this.resTlDragging = {
            mode: "create",
            rect,
            startX: ev.clientX,
            anchorMs: this.resTlPointMs(ev.clientX, rect),
            moved: false,
        };
        this.bindResTlDrag();
    }

    onResTlBarDown(item, ev) {
        if (ev.button !== 0) {
            return;
        }
        if (!item.mine) {
            // Other resources' bookings are view-only: a click still opens
            // the detail card so conflicts can be inspected.
            this.selectResAssignment(item);
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        const barRect = ev.currentTarget.getBoundingClientRect();
        const rect = ev.currentTarget.parentElement.getBoundingClientRect();
        const offset = ev.clientX - barRect.left;
        const mode = offset <= 6 ? "left"
            : barRect.width - offset <= 6 ? "right" : "move";
        const { s, e } = this.resTlItemMs(item);
        this.resTlDragging = {
            mode, item, rect,
            startX: ev.clientX,
            origS: s, origE: e,
            moved: false,
        };
        this.bindResTlDrag();
    }

    // The pending preview is itself movable/resizable before commit —
    // modes "pmove"/"pleft"/"pright" update resTlPending instead of writing.
    onResTlPendingDown(ev) {
        const pend = this.state.resTlPending;
        if (!pend || ev.button !== 0) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        const barRect = ev.currentTarget.getBoundingClientRect();
        const rect = ev.currentTarget.parentElement.getBoundingClientRect();
        const offset = ev.clientX - barRect.left;
        const mode = offset <= 6 ? "pleft"
            : barRect.width - offset <= 6 ? "pright" : "pmove";
        this.resTlDragging = {
            mode, rect,
            startX: ev.clientX,
            origS: pend.startMs, origE: pend.endMs,
            moved: false,
        };
        this.bindResTlDrag();
    }

    bindResTlDrag() {
        const onMove = (e) => this.onResTlDragMove(e);
        const onUp = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            window.removeEventListener("pointercancel", onUp);
            this.onResTlDragEnd();
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onUp);
    }

    onResTlDragMove(ev) {
        const d = this.resTlDragging;
        if (!d) {
            return;
        }
        const dx = ev.clientX - d.startX;
        if (!d.moved && Math.abs(dx) < 3) {
            return;
        }
        d.moved = true;
        const range = this.resTlRange;
        const msPerPx = (range.end.getTime() - range.start.getTime()) / d.rect.width;
        if (d.mode === "create") {
            const cur = this.resTlPointMs(ev.clientX, d.rect);
            const s = this.resTlSnap(Math.min(d.anchorMs, cur), "start");
            const e = this.resTlSnap(Math.max(d.anchorMs, cur), "end");
            this.state.resTlDrag = this.resTlDragState(s, e);
            return;
        }
        const delta = dx * msPerPx;
        if (d.mode === "pmove") {
            const unit = this.resTlUnitMs();
            const shift = Math.round(delta / unit) * unit;
            this.resTlPendingSet(d.origS + shift, d.origE + shift);
            return;
        }
        if (d.mode === "pleft") {
            const s = Math.min(this.resTlSnap(d.origS + delta, "start"), d.origE - 3600000);
            this.resTlPendingSet(s, d.origE);
            return;
        }
        if (d.mode === "pright") {
            const e = Math.max(this.resTlSnap(d.origE + delta, "end"), d.origS + 3600000);
            this.resTlPendingSet(d.origS, e);
            return;
        }
        if (d.mode === "move") {
            const unit = this.resTlUnitMs();
            const shift = Math.round(delta / unit) * unit;
            this.state.resTlDrag = this.resTlDragState(d.origS + shift, d.origE + shift);
            return;
        }
        if (d.mode === "left") {
            const s = Math.min(this.resTlSnap(d.origS + delta, "start"), d.origE - 3600000);
            this.state.resTlDrag = this.resTlDragState(s, d.origE);
            return;
        }
        const e = Math.max(this.resTlSnap(d.origE + delta, "end"), d.origS + 3600000);
        this.state.resTlDrag = this.resTlDragState(d.origS, e);
    }

    async onResTlDragEnd() {
        const d = this.resTlDragging;
        const drag = this.state.resTlDrag;
        this.resTlDragging = null;
        this.state.resTlDrag = null;
        if (!d?.moved) {
            // Click without drag on an own bar → select for the detail card.
            if (d?.item) {
                this.selectResAssignment(d.item);
            }
            return;
        }
        if (d.mode.startsWith("p")) {
            await this.updateResTlPendingEst();
            return;
        }
        if (!drag || drag.endMs <= drag.startMs) {
            return;
        }
        const startDt = fmtDt(new Date(drag.startMs));
        const endDt = fmtDt(new Date(drag.endMs));
        if (d.mode === "create") {
            // Dragging only stages a preview — the "Assign" button commits it.
            this.state.resTlPending = {
                startMs: drag.startMs,
                endMs: drag.endMs,
                conflict: drag.conflict,
                outside: drag.outside,
                estHours: null,
            };
            await this.updateResTlPendingEst();
            return;
        }
        try {
            await this.orm.call(
                "project.task", "planner_update_assignment", [this.state.resTask.id],
                {
                    assignment_id: d.item.id,
                    date_start: startDt,
                    date_end: endDt,
                },
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || _t("The assignment could not be updated."), { type: "danger" },
            );
            return;
        }
        if (drag.conflict) {
            this.notification.add(
                _t("Saved — the new position overlaps another assignment of this resource."),
                { type: "warning" },
            );
        }
        await this.refreshResources();
    }

    gripStyle(task, side) {
        const bar = this.barGeometry(task);
        if (!bar) {
            return "display:none";
        }
        const width = Math.min(8, bar.width);
        const left = side === "left" ? bar.left - 2 : bar.left + bar.width - width + 2;
        return `left:${left}px;width:${width}px`;
    }

    get dragTip() {
        const drag = this.state.drag;
        if (!drag) {
            return false;
        }
        const bar = this.spanGeometry(drag.start, drag.stop, drag.dtStart, drag.dtStop);
        if (!bar) {
            return false;
        }
        let text;
        if (this.state.scale === "day" && drag.dtStart && drag.dtStop) {
            const fmt = getCalendarFormats().time;
            text = `${fmt.format(parseDt(drag.dtStart))} – ${fmt.format(parseDt(drag.dtStop))}`;
        } else {
            const start = parseDay(drag.start);
            const stop = parseDay(drag.stop);
            text = `${dayLabel(start)} – ${dayLabel(stop)} · ${dayDiff(start, stop) + 1}d`;
        }
        return {
            style: `left:${bar.left}px;top:${Math.max(drag.rowIdx * PLANNER_ROW_H - 22, 0)}px`,
            text,
        };
    }

    // Clicking empty space (below/beside the task rows) clears the current
    // row selection; clicks inside a row or the inspector are ignored.
    onBackgroundClick(ev) {
        if (ev.target.closest(".o_cp_planner_wbs_row, .o_cp_planner_gantt_row, .o_cp_planner_dep_edit")) {
            return;
        }
        this.state.selectedId = null;
        this.state.inspectorOpen = false;
        this.state.depEdit = null;
    }

    onRowClick(task) {
        if (this.suppressClick) {
            this.suppressClick = false;
            return;
        }
        this.selectTask(task);
    }

    onGanttScroll() {
        const scrollEl = this.ganttScrollRef.el;
        const wbsEl = this.wbsRowsRef.el;
        if (scrollEl && wbsEl && wbsEl.scrollTop !== scrollEl.scrollTop) {
            wbsEl.scrollTop = scrollEl.scrollTop;
        }
        // Continuous timeline — grow the buffered range as the viewport
        // approaches either end so the axis never visibly cuts off.
        if (scrollEl) {
            const margin = scrollEl.clientWidth * 0.6;
            if (scrollEl.scrollLeft + scrollEl.clientWidth > this.timelineWidth - margin) {
                this.extendRange("right");
            } else if (scrollEl.scrollLeft < margin && this.state.rangeStart) {
                this.extendRange("left");
            }
        }
    }

    onWbsScroll() {
        const scrollEl = this.ganttScrollRef.el;
        const wbsEl = this.wbsRowsRef.el;
        if (scrollEl && wbsEl && scrollEl.scrollTop !== wbsEl.scrollTop) {
            scrollEl.scrollTop = wbsEl.scrollTop;
        }
    }

    // ------------------------------------------------------------------
    // Resource Board (BRD-19): project-wide capacity view reusing the
    // resource timeline metrics — view only, no drag/assign here.
    // ------------------------------------------------------------------

    boardAnchorDate() {
        if (this.state.boardAnchor) {
            return this.state.boardAnchor;
        }
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        return d;
    }

    setBoardMode(on) {
        this.state.boardMode = on;
        if (on && this.state.projectId) {
            this.loadBoard();
        } else if (!on) {
            this._pendingFit = true;
        }
    }

    async loadBoard() {
        if (!this.state.projectId) {
            return;
        }
        const range = this.boardRange;
        this.state.boardLoading = true;
        try {
            const data = await this.orm.call(
                "project.project", "planner_get_resource_board", [this.state.projectId],
                {
                    window_start: isoDay(range.start),
                    window_end: isoDay(addDays(range.end, -1)),
                },
            );
            this.state.boardResources = data.resources || [];
        } catch {
            this.state.boardResources = [];
            this.notification.add(_t("Resources could not be loaded."), { type: "danger" });
        } finally {
            this.state.boardLoading = false;
        }
    }

    get boardRange() {
        const anchor = this.boardAnchorDate();
        if (this.state.boardScale === "day") {
            return { start: anchor, end: addDays(anchor, 1) };
        }
        if (this.state.boardScale === "month") {
            const start = startOfMonth(anchor);
            const end = startOfMonth(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1));
            return { start, end };
        }
        const start = startOfWeek(anchor);
        return { start, end: addDays(start, 7) };
    }

    get boardColumns() {
        const range = this.boardRange;
        if (!range) {
            return [];
        }
        const cols = [];
        if (this.state.boardScale === "day") {
            for (let h = 0; h < 24; h++) {
                cols.push({ label: pad2(h) });
            }
        } else {
            for (let t = range.start.getTime(); t < range.end.getTime(); t += DAY_MS) {
                const d = new Date(t);
                cols.push({
                    label: this.state.boardScale === "month"
                        ? String(d.getDate())
                        : `${getCalendarFormats().weekdayShort.format(d)} ${pad2(d.getDate())}`,
                });
            }
        }
        return cols;
    }

    // Single-line caption above the column headers: day → "17 Eylül
    // Perşembe", week → "Eylül 2026 · Week 38", month → "Eylül 2026".
    get boardCaption() {
        const anchor = this.boardAnchorDate();
        if (this.state.boardScale === "month") {
            return getCalendarFormats().monthYear.format(anchor);
        }
        if (this.state.boardScale === "week") {
            return `${getCalendarFormats().monthYear.format(startOfWeek(anchor))} · ${_t("Week")} ${isoWeek(anchor)}`;
        }
        return getCalendarFormats().dayCaption.format(anchor);
    }

    boardMsToStyle(s, e) {
        const range = this.boardRange;
        if (!range) {
            return "display:none";
        }
        const span = range.end.getTime() - range.start.getTime();
        const left = Math.max((s - range.start.getTime()) / span * 100, 0);
        const width = Math.min((e - s) / span * 100, 100 - left);
        return `left:${left}%;width:${Math.max(width, 0.5)}%`;
    }

    boardItemStyle(item) {
        const { s, e } = this.resTlItemMs(item);
        return this.boardMsToStyle(s, e);
    }

    // Hover tooltip over a booking bar: task name, localized range,
    // duration and state — replaces the cramped native title.
    onBoardBarEnter(item, ev) {
        const container = ev.currentTarget.closest(".o_cp_board_tl");
        if (!container) {
            return;
        }
        const bar = ev.currentTarget.getBoundingClientRect();
        const box = container.getBoundingClientRect();
        const center = bar.left + bar.width / 2 - box.left + container.scrollLeft;
        const visibleTop = bar.top - box.top;
        const below = visibleTop < 110;
        const half = 124; // half of the tooltip's fixed width
        const minLeft = container.scrollLeft + half;
        const maxLeft = container.scrollLeft + container.clientWidth - half;
        this.state.boardTip = {
            item,
            left: Math.min(Math.max(center, minLeft), Math.max(maxLeft, minLeft)),
            top: below
                ? bar.top - box.top + container.scrollTop + bar.height + 6
                : bar.top - box.top + container.scrollTop - 6,
            below,
        };
    }

    onBoardBarLeave() {
        this.state.boardTip = null;
    }

    boardTipRange(item) {
        const { s, e } = this.resTlItemMs(item);
        const fmt = getCalendarFormats();
        const sd = new Date(s);
        const ed = new Date(e);
        const start = `${fmt.tipDate.format(sd)}, ${fmt.time.format(sd)}`;
        const end = isoDay(sd) === isoDay(ed)
            ? fmt.time.format(ed)
            : `${fmt.tipDate.format(ed)}, ${fmt.time.format(ed)}`;
        return `${start} → ${end}`;
    }

    boardTipDuration(item) {
        return `${_t("Duration")}: ${this.formatHours(item.planned_hours)}`;
    }

    boardTipStatus(item) {
        return `${_t("Status")}: ${item.task_state}`;
    }

    // Overview = one row per resource; selected = one row per booking,
    // same focus behaviour as the assignment dialog.
    get boardRows() {
        const sel = this.state.boardResources.find((res) => res.key === this.state.boardSelKey);
        if (sel) {
            return (sel.schedule || []).map((item) => ({
                key: item.id, label: item.task_name, title: item.task_name, items: [item],
            }));
        }
        return this.state.boardResources.map((res) => ({
            key: res.key, label: res.name, title: res.name, items: res.schedule || [], res,
        }));
    }

    get boardPersonnel() {
        return this.state.boardResources.filter((res) => res.category === "human");
    }

    get boardEquipment() {
        return this.state.boardResources.filter((res) => res.category === "equipment");
    }

    boardGroupCollapsed(key) {
        return this.state.boardGroupsCollapsed.has(key);
    }

    toggleBoardGroup(key) {
        const next = new Set(this.state.boardGroupsCollapsed);
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        this.state.boardGroupsCollapsed = next;
    }

    selectBoardResource(res) {
        this.state.boardSelKey = this.state.boardSelKey === res.key ? null : res.key;
    }



    async boardNavigate(dir) {
        const base = this.boardAnchorDate();
        if (this.state.boardScale === "month") {
            this.state.boardAnchor = new Date(base.getFullYear(), base.getMonth() + dir, 1);
        } else {
            this.state.boardAnchor = addDays(base, dir * (this.state.boardScale === "week" ? 7 : 1));
        }
        await this.loadBoard();
    }

    async boardToday() {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        this.state.boardAnchor = this.state.boardScale === "month" ? startOfMonth(d)
            : this.state.boardScale === "week" ? startOfWeek(d) : d;
        await this.loadBoard();
    }

    async setBoardScale(scale) {
        if (this.state.boardScale === scale) {
            return;
        }
        this.state.boardScale = scale;
        const cur = this.state.boardAnchor || new Date();
        this.state.boardAnchor = scale === "month" ? startOfMonth(cur)
            : scale === "week" ? startOfWeek(cur)
            : new Date(cur.getFullYear(), cur.getMonth(), cur.getDate());
        await this.loadBoard();
    }

    get boardPickerValue() {
        return isoDay(this.boardAnchorDate());
    }

    async onBoardDatePick(ev) {
        const val = ev.target.value;
        if (!val) {
            return;
        }
        const picked = parseDay(val);
        this.state.boardAnchor = this.state.boardScale === "month" ? startOfMonth(picked)
            : this.state.boardScale === "week" ? startOfWeek(picked) : picked;
        await this.loadBoard();
    }

    // BRD-22: one-click navigation back to the project's form — no list
    // detour, the same project record opens directly.
    openProjectForm() {
        if (!this.state.projectId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.project",
            res_id: this.state.projectId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async onProjectChange(ev) {
        this.state.projectId = Number(ev.target.value) || false;
        if (this.state.projectId) {
            // New project, new window — re-anchor it like the first load.
            this.state.anchor = null;
            await this.loadProject(this.state.projectId);
            // A different project means a different range — refit it.
            this.fit();
            if (this.state.boardMode) {
                this.state.boardSelKey = null;
                await this.loadBoard();
            }
        }
    }
}

registry.category("actions").add("project_critical_path.planner_workspace", PlannerWorkspace);
