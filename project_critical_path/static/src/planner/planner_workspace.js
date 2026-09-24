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
// The deep negative end exists for Fit: a multi-week project span must
// reach ~13 px/day to fit a ~900 px viewport on the day scale.
const ZOOM_MIN = -9;
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

// Standard Filters & Group By (BRD): the status/time filters each map to a
// project.task domain evaluated server-side — matching tasks keep their WBS
// ancestors so the tree stays readable. Group By only re-arranges the
// rendered rows; task data, hierarchy and scheduling never change.
const PLANNER_STATUS_FILTERS = [
    { key: "critical", label: _t("Critical Path") },
    { key: "overdue", label: _t("Overdue") },
    { key: "today", label: _t("Today") },
    { key: "week", label: _t("This Week") },
    { key: "done", label: _t("Completed") },
    { key: "notdone", label: _t("Not Completed") },
    // Finish Variance (BRD): server-side domain on the stored
    // finish_variance_state field — never display-text matching.
    { key: "doneLate", label: _t("Completed Late") },
    { key: "doneEarly", label: _t("Completed Early") },
    { key: "doneOnTime", label: _t("Completed On Time") },
];
const GROUP_BY_OPTIONS = [
    { key: "assignee", label: _t("Assignee") },
    { key: "role", label: _t("Role") },
    { key: "restype", label: _t("Resource Type") },
    { key: "stage", label: _t("Status") },
    { key: "wbs", label: _t("WBS / Parent") },
];
// Group-by choices backed by resource models — hidden while the
// project_resource_planning addon is not installed.
const RESOURCE_GROUP_KEYS = new Set(["role", "restype"]);
const EMPTY_FILTERS = () => ({
    critical: false, overdue: false, today: false, week: false,
    done: false, notdone: false,
    doneLate: false, doneEarly: false, doneOnTime: false,
    userId: false, roleId: false,
    resType: "", stageId: false, parentId: false, dateStart: "", dateStop: "",
});

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
// ---- Working-calendar (folded timeline) helpers --------------------------
// Folded by default like Odoo's gantt: non-working time stays visible as
// gray bands but compressed to a fraction of the working rate.
const GAP_RATE = 0.22; // intra-day off time (nights, lunch breaks)
const OFF_RATE = 0.08; // full non-working days (weekends, leaves)

const _tzDtf = new Map();
// UTC offset of `tz` at instant `ms` — resolved via Intl, no library.
function tzOffsetMs(tz, ms) {
    let dtf = _tzDtf.get(tz);
    if (!dtf) {
        dtf = new Intl.DateTimeFormat("en-US", {
            timeZone: tz, hourCycle: "h23",
            year: "numeric", month: "2-digit", day: "2-digit",
            hour: "2-digit", minute: "2-digit", second: "2-digit",
        });
        _tzDtf.set(tz, dtf);
    }
    const parts = dtf.formatToParts(new Date(ms));
    const g = (type) => Number(parts.find((p) => p.type === type).value);
    return Date.UTC(g("year"), g("month") - 1, g("day"), g("hour") % 24, g("minute"), g("second")) - ms;
}
// Wall-clock time in `tz` → absolute ms (two-pass so DST edges resolve).
function tzWallToMs(tz, y, mo, d, hFrac) {
    const h = Math.floor(hFrac);
    const mi = Math.round((hFrac - h) * 60);
    const wall = Date.UTC(y, mo, d, h, mi);
    return wall - tzOffsetMs(tz, wall - tzOffsetMs(tz, wall));
}
// Calendar-tz calendar day (y/m/d/weekday) containing the instant `ms`.
function tzDayAt(tz, ms) {
    const d = new Date(ms + tzOffsetMs(tz, ms));
    return { y: d.getUTCFullYear(), m: d.getUTCMonth(), d: d.getUTCDate(), wd: d.getUTCDay() };
}
const startOfDayMs = (ms) => {
    const d = new Date(ms);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
};

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
            // Project-level planning precision (BRD) — "hour" keeps the
            // existing date+time behaviour; "day" hides time pickers and
            // quantizes drags/resizes to whole days.
            planningPrecision: "hour",
            hoursPerDay: 8,
            // Project working calendar (BRD Folded Timeline) — attendances,
            // leaves and timezone straight from resource.calendar. False
            // keeps the timeline continuous/uncompressed.
            calendar: null,
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
            // WBS quick-create: the new child row enters inline rename mode
            // (Enter saves the name, Escape removes the just-created task).
            renamingId: null,
            // Multi-assignee tag picker in the Inspector (same m2m semantics
            // as the task form's Assignees field — chips + type-ahead).
            assigneeOpen: false,
            assigneeQuery: "",
            renameValue: "",
            // WBS drag reorder — ordering only, hierarchy never changes.
            wbsDragId: null,
            wbsDropBeforeId: null,
            wbsDropAfterId: null,
            // Bar info field selector (BRD-17) — per-project selection
            barInfoOpen: false,
            barInfoKeys: [...BAR_INFO_DEFAULT],
            // Slack chip pinned left of each bar (BRD-18) — per-project toggle
            slackVisible: true,
            // Toolbar task search — the submitted text becomes a simple
            // name/wbs_code ilike domain sent with get_planner_data
            searchDomain: [],
            // Standard Filters & Group By (BRD) — Odoo-style dropdowns.
            // Filter state is intentionally in-memory only: like standard
            // Odoo views, non-favorite filters reset on reload.
            filtersOpen: false,
            groupByOpen: false,
            filters: EMPTY_FILTERS(),
            groupBy: "",
            // Gantt viewport left edge — finish-variance flags read it to
            // flip inward before they would overflow the visible area.
            scrollLeft: 0,
            // Option lists for the dropdowns — full-project users, roles,
            // stages and root tasks (from the get_planner_data meta block).
            meta: { users: [], roles: [], stages: [], parents: [] },
            // BRD Planner Manager — read from the get_planner_data payload
            // (server-side group check). Default false = fail closed: until
            // a project payload confirms membership the workspace renders
            // read-only and every mutation entry point is blocked.
            canEdit: false,
            // False while project_resource_planning is not installed —
            // hides the Resource Board toggle, Material Plan shortcut,
            // resource filters and the inspector resource section.
            hasResources: false,
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
        this.statusFilters = PLANNER_STATUS_FILTERS;
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
            } else if (this.state.filtersOpen) {
                this.state.filtersOpen = false;
            } else if (this.state.groupByOpen) {
                this.state.groupByOpen = false;
            } else if (this.state.colMenuOpen) {
                this.state.colMenuOpen = false;
            }
        });
        useExternalListener(document.body, "click", (ev) => {
            if (this.state.colMenuOpen && !ev.target.closest(".o_cp_planner_colmenu")) {
                this.state.colMenuOpen = false;
            }
            if (this.state.filtersOpen && !ev.target.closest(".o_cp_planner_filtermenu")) {
                this.state.filtersOpen = false;
            }
            if (this.state.groupByOpen && !ev.target.closest(".o_cp_planner_groupbymenu")) {
                this.state.groupByOpen = false;
            }
            if (this.state.assigneeOpen && !ev.target.closest(".o_cp_planner_assignee")) {
                this.state.assigneeOpen = false;
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
                    el.scrollLeft = Math.max(
                        this.timeToX(anchor.ms) - anchor.frac * el.clientWidth, 0,
                    );
                }
                this._pendingZoomAnchor = null;
            }
            // WBS quick-create inline rename: focus the input once the new
            // child row has been patched in.
            if (this.state.renamingId) {
                const input = this.wbsRowsRef.el?.querySelector(".o_cp_planner_rename_input");
                if (input && document.activeElement !== input) {
                    input.focus();
                    input.select();
                }
            }
        });
        onMounted(async () => {
            try {
                const info = await this.orm.call("project.project", "get_planner_projects", []);
                this.state.projects = info.projects || [];
                this.state.hasResources = !!info.has_resource_planning;
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
            // Toolbar search text and the Filters dropdown build one AND-ed
            // domain — the backend keeps the WBS ancestors of every match.
            const domain = [
                ...(this.state.searchDomain || []),
                ...this.filterDomain,
            ];
            if (domain.length) {
                kwargs.domain = domain;
            }
            const data = await this.orm.call(
                "project.project", "get_planner_data", [projectId], kwargs,
            );
            this.state.projectName = data.project.name;
            // BRD Planning Precision — project-level hour/day planning
            // granularity. Display + input precision only; the scheduling
            // engine keeps working on stored datetimes.
            this.state.planningPrecision = data.project.planning_precision || "hour";
            this.state.hoursPerDay = data.project.hours_per_day || 8;
            // Working calendar — drives the folded timeline. Absent/false
            // keeps the continuous uncompressed layout.
            this.state.calendar = data.project.calendar || null;
            // BRD Planner Manager — authoritative flag from the server.
            // Absent/false keeps the workspace read-only (fail closed).
            this.state.canEdit = !!data.is_planner_manager;
            this.state.tasks = data.tasks;
            if (data.meta) {
                this.state.meta = data.meta;
            }
            this.computeRange();
        } catch (error) {
            this.state.tasks = [];
            this.notification.add(error.data?.message || _t("The planner data could not be loaded."), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    // BRD Planner Manager — single front-end gate for every mutation entry
    // point. The server enforces the group on each RPC too; this check only
    // keeps the UI honest (and fails closed while canEdit is unresolved).
    _guardEdit() {
        if (this.state.canEdit) {
            return true;
        }
        this.notification.add(
            _t("Only Planner Managers can modify planner data."),
            { type: "warning" },
        );
        return false;
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

    // ---- Folded timeline (working calendar) -------------------------------
    // Piecewise time→px map over the planner range: contiguous segments
    // each with their own px/ms rate. Working intervals run at full rate,
    // intra-day off-time (nights/lunch) is compressed light-gray "gap",
    // full non-working days are compressed darker "off". No calendar → a
    // single work segment, identical to the old continuous layout.
    get timeMap() {
        const range = this.plannerRange;
        const cal = this.state.calendar;
        const key = [
            this.state.scale,
            range.start.getTime(),
            range.end.getTime(),
            this.state.pxPerDay,
            cal?.id || 0,
        ].join("|");
        if (this._mapKey === key) {
            return this._mapCache;
        }
        this._mapCache = this._buildTimeMap(range, cal);
        this._mapKey = key;
        return this._mapCache;
    }

    _buildTimeMap(range, cal) {
        const t0 = range.start.getTime();
        const t1 = range.end.getTime();
        const segs = [];
        if (!cal || !cal.attendances?.length) {
            segs.push({ t0, t1, kind: "work" });
        } else {
            const leaves = cal.leaves.map((l) => [
                Date.parse(l.from.replace(" ", "T") + "Z"),
                Date.parse(l.to.replace(" ", "T") + "Z"),
            ]);
            // Iterate real local day boundaries (calendar arithmetic) so
            // DST-shortened/lengthened days stay aligned.
            for (let d0 = t0, guard = 0; d0 < t1 && guard++ < 5000;) {
                const dd = new Date(d0);
                const d1 = Math.min(
                    new Date(dd.getFullYear(), dd.getMonth(), dd.getDate() + 1).getTime(),
                    t1,
                );
                // Calendar-tz date at local noon — avoids midnight edge cases.
                const cday = tzDayAt(cal.tz, d0 + DAY_MS / 2);
                // Odoo dayofweek is 0=Mon..6=Sun; JS getUTCDay is
                // 0=Sun..6=Sat — rebase to Odoo's convention.
                const odooWd = (cday.wd + 6) % 7;
                // Two-week calendars alternate attendances by week parity
                // (ISO-week parity approximates Odoo's week_type rhythm).
                const parity = cal.twoWeeks ? isoWeek(new Date(d0)) % 2 : null;
                let ints = cal.attendances
                    .filter((a) => a.weekday === odooWd
                        && (parity === null || a.weekType === "" || Number(a.weekType) === parity))
                    .map((a) => [
                        tzWallToMs(cal.tz, cday.y, cday.m, cday.d, a.from),
                        tzWallToMs(cal.tz, cday.y, cday.m, cday.d, a.to),
                    ])
                    .map(([a, b]) => [Math.max(a, d0), Math.min(b, d1)])
                    .filter(([a, b]) => b > a)
                    .sort((x, y) => x[0] - y[0]);
                // Subtract calendar/global leaves from the day's intervals.
                for (const [lf, lt] of leaves) {
                    if (lt <= d0 || lf >= d1) {
                        continue;
                    }
                    ints = ints.flatMap(([a, b]) => {
                        if (lt <= a || lf >= b) {
                            return [[a, b]];
                        }
                        const out = [];
                        if (lf > a) {
                            out.push([a, lf]);
                        }
                        if (lt < b) {
                            out.push([lt, b]);
                        }
                        return out;
                    });
                }
                // Merge overlapping/adjacent intervals.
                const merged = [];
                for (const [a, b] of ints) {
                    const last = merged[merged.length - 1];
                    if (last && a <= last[1]) {
                        last[1] = Math.max(last[1], b);
                    } else {
                        merged.push([a, b]);
                    }
                }
                if (!merged.length) {
                    segs.push({ t0: d0, t1: d1, kind: "off" });
                } else {
                    let cur = d0;
                    for (const [a, b] of merged) {
                        if (a > cur) {
                            segs.push({ t0: cur, t1: a, kind: "gap" });
                        }
                        segs.push({ t0: a, t1: b, kind: "work" });
                        cur = b;
                    }
                    if (cur < d1) {
                        segs.push({ t0: cur, t1: d1, kind: "gap" });
                    }
                }
                d0 = d1;
            }
        }
        // Assign pixels — compressed rates keep a minimum width so every
        // folded region is wide enough to host the "◄ ►" marker, like
        // Odoo's collapsed columns (~one hour cell at day zoom).
        const rate = this.state.pxPerDay / DAY_MS;
        const gapMin = Math.min(26, this.state.pxPerDay * 0.08);
        const offMin = Math.min(26, this.state.pxPerDay * 0.4);
        let px = 0;
        for (const seg of segs) {
            const factor = seg.kind === "work" ? 1 : seg.kind === "gap" ? GAP_RATE : OFF_RATE;
            const min = seg.kind === "gap" ? gapMin : seg.kind === "off" ? offMin : 0;
            const w = Math.max((seg.t1 - seg.t0) * rate * factor, min);
            seg.px0 = px;
            px += w;
            seg.px1 = px;
            seg.rate = w / (seg.t1 - seg.t0);
        }
        return { segs, width: px, t0, t1 };
    }

    // Central datetime→px mapping — every renderer (bars, arrows, today
    // marker, columns, tails) goes through this so they always agree.
    timeToX(ms) {
        const { segs } = this.timeMap;
        if (!segs.length) {
            return 0;
        }
        if (ms <= segs[0].t0) {
            return segs[0].px0 + (ms - segs[0].t0) * segs[0].rate;
        }
        let lo = 0, hi = segs.length - 1;
        while (lo < hi) {
            const mid = (lo + hi + 1) >> 1;
            if (segs[mid].t0 <= ms) {
                lo = mid;
            } else {
                hi = mid - 1;
            }
        }
        const seg = segs[lo];
        return seg.px0 + (ms - seg.t0) * seg.rate;
    }

    // Inverse mapping — drags, resizes and zoom anchors land on real
    // datetimes even inside compressed regions.
    xToTime(px) {
        const { segs } = this.timeMap;
        if (!segs.length) {
            return 0;
        }
        if (px <= 0) {
            return segs[0].t0 + px / segs[0].rate;
        }
        let lo = 0, hi = segs.length - 1;
        while (lo < hi) {
            const mid = (lo + hi + 1) >> 1;
            if (segs[mid].px0 <= px) {
                lo = mid;
            } else {
                hi = mid - 1;
            }
        }
        const seg = segs[lo];
        return seg.t0 + (px - seg.px0) / seg.rate;
    }

    // Folded non-working regions painted behind the rows — light for
    // intra-day gaps (nights/lunch), darker for full off days.
    get offRegions() {
        const out = [];
        for (const seg of this.timeMap.segs) {
            if (seg.kind === "work") {
                continue;
            }
            const w = seg.px1 - seg.px0;
            if (w < 0.4) {
                continue;
            }
            out.push({ left: seg.px0, width: w, kind: seg.kind });
        }
        return out;
    }

    // Segment kind at an instant — used to dim off-day column headers.
    _segKindAt(ms) {
        const { segs } = this.timeMap;
        let lo = 0, hi = segs.length - 1;
        while (lo < hi) {
            const mid = (lo + hi + 1) >> 1;
            if (segs[mid].t0 <= ms) {
                lo = mid;
            } else {
                hi = mid - 1;
            }
        }
        return segs[lo].kind;
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

    // ---- Standard Filters & Group By (BRD) ---------------------------------
    // Filters build a project.task domain evaluated server-side; Group By
    // only re-arranges rendered rows. Neither ever writes task data.

    get hasActiveFilters() {
        const f = this.state.filters;
        return !!(
            f.critical || f.overdue || f.today || f.week || f.done || f.notdone
            || f.doneLate || f.doneEarly || f.doneOnTime
            || f.userId || f.roleId || f.resType || f.stageId || f.parentId
            || f.dateStart || f.dateStop
        );
    }

    get activeFilterCount() {
        const f = this.state.filters;
        return [
            f.critical, f.overdue, f.today, f.week, f.done, f.notdone,
            f.doneLate, f.doneEarly, f.doneOnTime,
            f.userId, f.roleId, f.resType, f.stageId, f.parentId,
            f.dateStart, f.dateStop,
        ].filter(Boolean).length;
    }

    // Status/time filters as a project.task domain. Date bounds are local
    // day boundaries; the backend keeps the WBS ancestors of every match.
    get filterDomain() {
        const f = this.state.filters;
        const dom = [];
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        if (f.critical) {
            dom.push(["is_critical", "=", true]);
        }
        if (f.overdue) {
            dom.push(
                ["date_deadline", "!=", false],
                ["date_deadline", "<", isoDay(today)],
                ["state", "!=", "1_done"],
            );
        }
        if (f.today) {
            dom.push(
                ["date_assign", "<=", `${isoDay(today)} 23:59:59`],
                ["date_deadline", ">=", isoDay(today)],
            );
        }
        if (f.week) {
            const weekStart = startOfWeek(today);
            const weekEnd = addDays(weekStart, 6);
            dom.push(
                ["date_assign", "<=", `${isoDay(weekEnd)} 23:59:59`],
                ["date_deadline", ">=", isoDay(weekStart)],
            );
        }
        if (f.done) {
            dom.push(["state", "=", "1_done"]);
        }
        if (f.notdone) {
            dom.push(["state", "!=", "1_done"]);
        }
        // Finish Variance (BRD) — the stored finish_variance_state field
        // already encodes "done and late/early/on-time".
        if (f.doneLate) {
            dom.push(["finish_variance_state", "=", "late"]);
        }
        if (f.doneEarly) {
            dom.push(["finish_variance_state", "=", "early"]);
        }
        if (f.doneOnTime) {
            dom.push(["finish_variance_state", "=", "on_time"]);
        }
        if (f.userId === "none") {
            dom.push(["user_ids", "=", false]);
        } else if (f.userId) {
            dom.push(["user_ids", "in", [f.userId]]);
        }
        if (this.state.hasResources && f.roleId) {
            dom.push(["resource_requirement_ids.role_id", "in", [f.roleId]]);
        }
        if (this.state.hasResources && f.resType) {
            dom.push(["resource_requirement_ids.role_id.category", "=", f.resType]);
        }
        if (f.stageId) {
            dom.push(["stage_id", "in", [f.stageId]]);
        }
        if (f.parentId) {
            dom.push(["id", "child_of", f.parentId]);
        }
        if (f.dateStart) {
            dom.push(["date_assign", ">=", f.dateStart]);
        }
        if (f.dateStop) {
            dom.push(["date_deadline", "<=", `${f.dateStop} 23:59:59`]);
        }
        return dom;
    }

    async applyFilters() {
        if (this.state.projectId) {
            await this.loadProject(this.state.projectId);
        }
    }

    async toggleStatusFilter(key) {
        this.state.filters[key] = !this.state.filters[key];
        await this.applyFilters();
    }

    async setFilterField(key, value) {
        this.state.filters[key] = value;
        await this.applyFilters();
    }

    onFilterSelect(key, ev) {
        const raw = ev.target.value;
        // resType carries string values ("human"/"equipment"); the id-based
        // selects carry numbers. "none" = the explicit Unassigned filter.
        const value = raw === "" ? (key === "resType" ? "" : false)
            : raw === "none" ? "none"
            : key === "resType" ? raw : Number(raw);
        this.setFilterField(key, value);
    }

    onFilterDate(key, ev) {
        this.setFilterField(key, ev.target.value || "");
    }

    async clearFilters() {
        this.state.filters = EMPTY_FILTERS();
        await this.applyFilters();
    }

    setGroupBy(key) {
        this.state.groupBy = this.state.groupBy === key ? "" : key;
    }

    // The key+label a task belongs to under the active Group By. Tasks
    // never duplicate across groups: multi-valued fields join into one
    // label, empty values land in a trailing "Undefined"-style group.
    taskGroup(task, groupBy) {
        const none = { key: "__none__" };
        switch (groupBy) {
            case "assignee":
                return task.user_names?.length
                    ? { key: `u${task.user_ids[0]}`, label: task.user_names.join(", ") }
                    : { ...none, label: _t("Unassigned") };
            case "role":
                return task.role_names?.length
                    ? { key: `r:${task.role_names.join("|")}`, label: task.role_names.join(", ") }
                    : { ...none, label: _t("No Role") };
            case "restype": {
                const cats = task.role_categories || [];
                const key = cats.length > 1 ? "both" : cats[0] || "__none__";
                const label = {
                    both: _t("Human + Equipment"),
                    human: _t("Human"),
                    equipment: _t("Equipment"),
                    __none__: _t("No Resource"),
                }[key];
                return { key, label };
            }
            case "stage":
                return task.stage_name
                    ? { key: `s:${task.stage_name}`, label: task.stage_name }
                    : { ...none, label: _t("No Stage") };
            case "wbs": {
                // Group under the top-level WBS ancestor (the task itself
                // when it is already a root).
                const byId = this.taskById;
                let root = task;
                while (root.parent_id && byId.get(root.parent_id)) {
                    root = byId.get(root.parent_id);
                }
                return { key: `p${root.id}`, label: `${root.wbs_code} ${root.name}` };
            }
        }
        return { ...none, label: _t("Other") };
    }

    // Rows rendered by BOTH panels: group headers interleaved with task
    // rows while Group By is active, otherwise a plain pass-through so row
    // indices, connectors and row heights stay exactly as before.
    get displayRows() {
        const tasks = this.visibleTasks;
        const groupBy = this.state.groupBy;
        if (!groupBy) {
            return tasks.map((task) => ({ type: "task", task, key: `t${task.id}` }));
        }
        const groups = new Map();
        for (const task of tasks) {
            const g = this.taskGroup(task, groupBy);
            let group = groups.get(g.key);
            if (!group) {
                group = { key: g.key, label: g.label, count: 0 };
                groups.set(g.key, group);
            }
            group.count += 1;
            group.tasks = group.tasks || [];
            group.tasks.push(task);
        }
        const ordered = [...groups.values()].sort((a, b) => {
            if (a.key === "__none__") {
                return 1;
            }
            if (b.key === "__none__") {
                return -1;
            }
            return a.label.localeCompare(b.label);
        });
        const rows = [];
        for (const group of ordered) {
            rows.push({ type: "group", key: `g:${group.key}`, label: group.label, count: group.count });
            for (const task of group.tasks) {
                rows.push({ type: "task", task, key: `t${task.id}` });
            }
        }
        return rows;
    }

    // Rendered row index per task — group headers occupy rows too, so the
    // dependency connector Y positions and the drag tooltip must index
    // into displayRows, not visibleTasks.
    get rowIndexById() {
        const map = new Map();
        this.displayRows.forEach((row, i) => {
            if (row.type === "task") {
                map.set(row.task.id, i);
            }
        });
        return map;
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
            this.state.calendar?.id || 0,
        ].join("|");
        if (this._colsKey === key) {
            return this._colsCache;
        }
        const cols = [];
        if (this.state.scale === "day" && this.state.calendar) {
            // Odoo-gantt style: each working hour is a labelled cell, while
            // every run of non-working segments collapses into ONE column
            // carrying the "◄ ►" marker — so the night merges across the
            // midnight boundary exactly like the standard gantt.
            const { segs } = this.timeMap;
            let run = null;
            const flushRun = () => {
                if (run) {
                    cols.push({
                        mark: true,
                        off: true,
                        width: this.timeToX(run[1]) - this.timeToX(run[0]),
                    });
                    run = null;
                }
            };
            for (const seg of segs) {
                if (seg.kind !== "work") {
                    run = run ? [run[0], seg.t1] : [seg.t0, seg.t1];
                    continue;
                }
                flushRun();
                for (let h = seg.t0; h < seg.t1;) {
                    const nxt = Math.min(
                        Math.floor(h / 3600000) * 3600000 + 3600000, seg.t1
                    );
                    cols.push({
                        label: pad2(new Date(h).getHours()),
                        width: this.timeToX(nxt) - this.timeToX(h),
                        off: false,
                    });
                    h = nxt;
                }
            }
            flushRun();
        } else if (this.state.scale === "day") {
            for (let t = range.start.getTime(); t < range.end.getTime(); t += DAY_MS) {
                for (let h = 0; h < 24; h++) {
                    cols.push({
                        label: pad2(h),
                        width: this.timeToX(t + (h + 1) * 3600000) - this.timeToX(t + h * 3600000),
                        off: false,
                    });
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
                    width: this.timeToX(t + DAY_MS) - this.timeToX(t),
                    off: this._segKindAt(t + DAY_MS / 2) === "off",
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
            this.state.calendar?.id || 0,
        ].join("|");
        if (this._groupsKey === key) {
            return this._groupsCache;
        }
        const fmt = getCalendarFormats();
        const groups = [];
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
                width: Math.max(this.timeToX(clipped) - this.timeToX(t), 0.5),
            });
            t = clipped;
        }
        this._groupsKey = key;
        this._groupsCache = groups;
        return groups;
    }

    get timelineWidth() {
        return Math.max(this.timeMap.width, 1);
    }

    get todayLeft() {
        const range = this.plannerRange;
        const now = new Date();
        if (now.getTime() < range.start.getTime() || now.getTime() >= range.end.getTime()) {
            return -9999;
        }
        return this.timeToX(now.getTime());
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
        let startMs, stopMs;
        if (this.state.scale === "day") {
            // Hour precision across the folded range: real stored times
            // when the payload carries them, otherwise the 09:00–18:00
            // convention (same as the resource timelines).
            startMs = dtStart
                ? parseDt(dtStart).getTime()
                : start.getTime() + 9 * 3600000;
            stopMs = dtStop
                ? parseDt(dtStop).getTime()
                : stop.getTime() + 18 * 3600000;
        } else {
            // Day precision: start at the day's start, end inclusive.
            startMs = start.getTime();
            stopMs = stop.getTime() + DAY_MS;
        }
        const left = Math.max(this.timeToX(startMs), 0);
        const right = Math.min(this.timeToX(stopMs), this.timelineWidth);
        return { left, width: Math.max(right - left, 1) };
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
        let title = task.is_critical ? `${task.name} — ${_t("Critical Path")}` : task.name;
        if (task.date_done) {
            title += `\n${this.finishTailTooltip(task).split("\n").slice(1).join("\n")}`;
        }
        return title;
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
        const left = this.timeToX(parseDay(task.baseline_stop).getTime() + DAY_MS);
        const right = this.timeToX(parseDay(dates.stop).getTime() + DAY_MS);
        return { left, width: Math.max(right - left, 1) };
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

    // ---- Finish Variance Tail (BRD v2) -----------------------------------
    // Red right tail when the task closed after its planned finish, green
    // tail inside the bar end when it closed early. The variance is
    // calendar-day based — the hour component never counts, so a same-day
    // close at 22:00 against an 18:00 plan is still on time. Identical
    // day math on every scale keeps the tail fixed across zoom changes.

    finishTail(task) {
        if (!task.date_done || !task.date_start || !task.date_stop) {
            return false;
        }
        const dates = this.currentDates(task);
        const stop = parseDay(dates.stop);
        const done = parseDay(task.date_done);
        const diff = dayDiff(stop, done); // >0 late, <0 early
        if (!diff) {
            return false;
        }
        const stopEndMs = stop.getTime() + DAY_MS;
        let tail;
        if (diff > 0) {
            // Late tail starts at the bar's right edge (stop day included).
            const left = this.timeToX(stopEndMs);
            const right = this.timeToX(done.getTime() + DAY_MS);
            if (left >= this.timelineWidth || right <= 0) {
                return false;
            }
            tail = { left, width: Math.max(right - left, 1.5), kind: "late" };
        } else {
            // Early tail sits inside the bar: actual close day → finish day.
            const left = this.timeToX(done.getTime());
            const right = this.timeToX(stopEndMs);
            if (left >= this.timelineWidth || right <= 0) {
                return false;
            }
            tail = { left, width: Math.max(right - left, 1.5), kind: "early" };
        }
        // Flag (BRD v2 §5-6): the "+Ng/-Ng" pill sits BELOW the bar at the
        // tail tip so it can never cover CP/lag/bar-info labels. It flips
        // inward when the pill would leave the gantt viewport — it must
        // never cross into the sticky WBS panel or past the canvas edge.
        tail.label = this.finishVarianceLabel(task);
        const scrollEl = this.ganttScrollRef?.el;
        const vpLeft = scrollEl ? this.state.scrollLeft || 0 : 0;
        const vpRight = scrollEl
            ? (this.state.scrollLeft || 0) + scrollEl.clientWidth
            : this.timelineWidth;
        const flagW = tail.label ? tail.label.length * 7 + 10 : 0;
        const tipX = tail.kind === "late" ? tail.left + tail.width : tail.left;
        tail.flip = tail.kind === "late"
            ? tipX + flagW / 2 > vpRight
            : tipX - flagW / 2 < vpLeft;
        return tail;
    }

    finishTailStyle(task) {
        const tail = this.finishTail(task);
        if (!tail) {
            return "display:none";
        }
        return `left:${tail.left}px;width:${tail.width}px`;
    }

    finishTailClass(task) {
        const tail = this.finishTail(task);
        if (!tail) {
            return "";
        }
        return `${tail.kind}${tail.flip ? " flip" : ""}`;
    }

    // Calendar-day variance — BRD v2 §3: date(date_done) - date(date_stop).
    _finishVarianceDays(task) {
        if (!task.date_done || !task.date_stop) {
            return 0;
        }
        return dayDiff(parseDay(task.date_stop), parseDay(task.date_done));
    }

    // Flag label (BRD v2 §6): "+4g"/"-2g"; "0g" is never shown.
    finishVarianceLabel(task) {
        const days = this._finishVarianceDays(task);
        if (!days) {
            return "";
        }
        return `${days > 0 ? "+" : "-"}${Math.abs(days)}g`;
    }

    // Tooltip/inspector text (BRD v2 §8-9): whole days only — "+4 days",
    // "-2 days", "0 days" when the task closed exactly on plan.
    finishVarianceText(task) {
        const days = this._finishVarianceDays(task);
        const sign = days > 0 ? "+" : days < 0 ? "-" : "";
        return `${sign}${Math.abs(days)} ${_t("days")}`;
    }

    finishTailTooltip(task) {
        return `${task.name}\n${_t("Done")}\n`
            + `${_t("Planned Finish")}: ${dayLabel(parseDay(task.date_stop))}\n`
            + `${_t("Actual Finish")}: ${dayLabel(parseDay(task.date_done))}\n`
            + `${_t("Finish Variance")}: ${this.finishVarianceText(task)}`;
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
        // Row positions come from displayRows so Group By header rows shift
        // the connector endpoints along with the task rows they sit above.
        const indexById = this.rowIndexById;
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
                parts.push(this.lagText(edge.dep.lag, edge.dep.unit));
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
            ms: pending ? pending.ms : this.xToTime(centerPx),
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
        // All segment rates scale linearly with pxPerDay, so the required
        // density is proportional to the current mapped span width.
        const spanPx = Math.max(this.timeToX(stopMs) - this.timeToX(startMs), 1);
        const base = this._zoomBase[this.state.scale] || this.state.pxPerDay;
        const target = this.state.pxPerDay * Math.max(el.clientWidth - 80, 200) / spanPx;
        const level = Math.min(Math.max(
            Math.round(Math.log(target / base) / Math.log(ZOOM_FACTOR)),
            ZOOM_MIN,
        ), ZOOM_MAX);
        this.state.zoom[this.state.scale] = level;
        const ppd = this.zoomDensity(this.state.scale);
        if (ppd === this.state.pxPerDay) {
            // No re-render — nothing will consume a pending anchor.
            el.scrollLeft = Math.max(this.timeToX(startMs) - 0.05 * el.clientWidth, 0);
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
        const px = this.timeToX(date.getTime());
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
        // scroll position so the view does not jump (see onPatched). The
        // prepended width comes from the folded map, already rebuilt on
        // the new range.
        this._leftExtendPx = (this._leftExtendPx || 0)
            + this.timeToX(oldStart.getTime());
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
            this.state.assigneeOpen = false;
            this.state.assigneeQuery = "";
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
                // Multi-assignee — same m2m semantics as the task form.
                user_ids: [...(t.user_ids || [])],
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
        this.state.assigneeOpen = false;
        this.state.assigneeQuery = "";
    }

    // Inspector multi-assignee — tag picker mirroring the task form's
    // Assignees m2m: selected users render as chips, typing filters the
    // remaining candidates, Enter picks the first match.
    get assigneeTags() {
        const ids = this.state.form?.user_ids || [];
        return (this.state.options?.users || []).filter((u) => ids.includes(u.id));
    }

    get assigneeCandidates() {
        const ids = this.state.form?.user_ids || [];
        const query = (this.state.assigneeQuery || "").toLowerCase().trim();
        return (this.state.options?.users || []).filter(
            (u) => !ids.includes(u.id)
                && (!query || (u.name || "").toLowerCase().includes(query))
        );
    }

    addAssignee(uid) {
        if (!this._guardEdit()) {
            return;
        }
        const form = this.state.form;
        if (!form) {
            return;
        }
        const ids = form.user_ids || (form.user_ids = []);
        if (!ids.includes(uid)) {
            ids.push(uid);
        }
        this.state.assigneeQuery = "";
        this.state.assigneeOpen = true;
    }

    removeAssignee(uid) {
        if (!this._guardEdit()) {
            return;
        }
        const ids = this.state.form?.user_ids;
        const index = ids ? ids.indexOf(uid) : -1;
        if (index >= 0) {
            ids.splice(index, 1);
        }
    }

    onAssigneeKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            const first = this.assigneeCandidates[0];
            if (first) {
                this.addAssignee(first.id);
            }
        } else if (
            ev.key === "Backspace"
            && !this.state.assigneeQuery
            && this.state.form?.user_ids?.length
        ) {
            // Same ergonomics as many2many_tags: Backspace on an empty
            // input pops the last chip.
            this.state.form.user_ids.pop();
        }
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

    // Finish Variance (BRD §10): day difference between the planned finish
    // and the effective actual close shown in the Inspector section.
    get inspectorFinishVariance() {
        const inspector = this.state.inspector;
        if (!inspector?.date_done || !inspector?.date_stop) {
            return false;
        }
        return dayDiff(parseDay(inspector.date_stop), parseDay(inspector.date_done));
    }

    // "+4 days" / "−2 days" / "+4 hours" — the inspector shows the same
    // day+hour decomposition as the tail tooltip.
    get inspectorFinishVarianceText() {
        const inspector = this.state.inspector;
        if (!inspector?.date_done) {
            return "";
        }
        return this.finishVarianceText(inspector);
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

    // Day-precision duration input — inclusive calendar days; changing it
    // stretches the finish date, keeping start fixed (BRD §6).
    onDayDurationChange(ev) {
        const form = this.state.form;
        form.duration_days = Math.max(Math.round(Number(ev.target.value) || 0), 1);
        if (form.date_start) {
            form.date_stop = isoDay(
                addDays(parseDay(form.date_start), form.duration_days - 1),
            );
        }
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
            parts.push(this.lagText(edge.lag, edge.unit));
        }
        return `· ${parts.join(" ")}`;
    }

    openDepEditor(taskId, predId, ev) {
        ev.stopPropagation();
        if (!this._guardEdit()) {
            return;
        }
        const edge = this.depEdge(taskId, predId);
        this.state.depEdit = {
            taskId,
            predId,
            type: edge?.type || "fs",
            lag: edge?.lag || 0,
            unit: edge?.unit || (this.isDayPrecision ? "days" : "hours"),
            x: ev.clientX,
            y: ev.clientY,
        };
    }

    closeDepEdit() {
        this.state.depEdit = null;
    }

    async saveDepEdit() {
        const edit = this.state.depEdit;
        if (!edit || !this._guardEdit()) {
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
        if ((!taskId && !isDraft) || !form || !this._guardEdit()) {
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
            // Day precision: time pickers are hidden — the write always
            // uses the canonical 09:00/18:00 boundary and only the date
            // parts decide whether the plan changed (BRD §7, §20).
            const dayMode = this.isDayPrecision;
            const startChanged = isDraft
                || (form.date_start || "") !== (inspector.date_start || "")
                || (!dayMode
                    && (form.time_start || "09:00")
                        !== ((inspector.dt_start || "").slice(11, 16) || "09:00"));
            const stopChanged = isDraft
                || (form.date_stop || "") !== (inspector.date_stop || "")
                || (!dayMode
                    && (form.time_stop || "18:00")
                        !== ((inspector.dt_stop || "").slice(11, 16) || "18:00"));
            await this.orm.call("project.task", "update_planner_task", [savedId], {
                values: {
                    name: name,
                    ...(startChanged ? {
                        date_start: form.date_start || false,
                        dt_start: form.date_start
                            ? `${form.date_start} ${dayMode ? "09:00" : (form.time_start || "09:00")}`
                            : false,
                    } : {}),
                    ...(stopChanged ? {
                        date_stop: form.date_stop || false,
                        // Time-of-day input — written with dt precision so
                        // the day-scale timeline shows the exact clock time.
                        dt_stop: form.date_stop
                            ? `${form.date_stop} ${dayMode ? "18:00" : (form.time_stop || "18:00")}`
                            : false,
                    } : {}),
                    duration_days: form.duration_days,
                    // Day precision edits duration in days — the server
                    // derives allocated_hours from the inclusive day span;
                    // sending the stale hour value would win over it.
                    ...(dayMode ? {} : { allocated_hours: form.allocated_hours }),
                    progress: form.progress || 0,
                    user_ids: form.user_ids || [],
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

    // BRD (WBS quick create): the small "+" next to each WBS row creates a
    // child task immediately and puts its name into inline edit mode —
    // Enter commits the name, Escape removes the just-created task so no
    // half-made record is left behind. Resource assignment stays in the
    // Inspector.
    async quickAddSubtask(task, ev) {
        ev.stopPropagation();
        if (!this._guardEdit()) {
            return;
        }
        try {
            const created = await this.orm.call(
                "project.task", "planner_add_subtask", [task.id], { name: "" },
            );
            this.state.collapsedIds.delete(task.id);
            await this.loadProject(this.state.projectId);
            this.state.selectedId = created.id;
            this.state.renamingId = created.id;
            this.state.renameValue = created.name;
        } catch (error) {
            this.notification.add(error.data?.message || _t("The subtask could not be created."), {
                type: "danger",
            });
        }
    }

    onRenameKeydown(task, ev) {
        ev.stopPropagation();
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.commitRename(task);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.cancelRename(task);
        }
    }

    async commitRename(task) {
        if (this.state.renamingId !== task.id || !this._guardEdit()) {
            return;
        }
        this.state.renamingId = null;
        const name = (this.state.renameValue || "").trim();
        if (!name || name === task.name) {
            return;
        }
        try {
            await this.orm.write("project.task", [task.id], { name });
            await this.loadProject(this.state.projectId);
            this.state.selectedId = task.id;
        } catch (error) {
            this.notification.add(error.data?.message || _t("The task could not be renamed."), {
                type: "danger",
            });
        }
    }

    async cancelRename(task) {
        if (this.state.renamingId !== task.id || !this._guardEdit()) {
            return;
        }
        this.state.renamingId = null;
        try {
            await this.orm.unlink("project.task", [task.id]);
            await this.loadProject(this.state.projectId);
        } catch (error) {
            this.notification.add(error.data?.message || _t("The task could not be removed."), {
                type: "danger",
            });
        }
    }

    // ---- WBS Indent / Outdent ----------------------------------------------
    // Hierarchy changes are explicit button actions only — the WBS drag
    // gesture is ordering-only and can never reparent a task (BRD).

    get selectedWbsTask() {
        return this.taskById.get(this.state.selectedId) || null;
    }

    get canIndent() {
        const task = this.selectedWbsTask;
        if (!task || this.state.renamingId) {
            return false;
        }
        // Under an active filter/grouping the visible sibling list is
        // incomplete — let the backend decide using the REAL WBS hierarchy
        // (it returns False for a first sibling instead of guessing from
        // the filtered rows).
        if (this.hasActiveFilters || this.state.groupBy) {
            return true;
        }
        const siblings = this.state.tasks.filter((row) => row.parent_id === task.parent_id);
        return siblings.findIndex((row) => row.id === task.id) > 0;
    }

    get canOutdent() {
        const task = this.selectedWbsTask;
        return !!task && !!task.parent_id && !this.state.renamingId;
    }

    async indentTask() {
        const task = this.selectedWbsTask;
        if (!task || !this.canIndent || !this._guardEdit()) {
            return;
        }
        try {
            const result = await this.orm.call("project.task", "planner_wbs_indent", [task.id]);
            if (result === false) {
                // Real WBS has no previous sibling to nest under — possible
                // while a filter hides siblings.
                this.notification.add(_t("The task cannot be indented here."), {
                    type: "warning",
                });
                return;
            }
            await this.loadProject(this.state.projectId);
            this.state.selectedId = task.id;
        } catch (error) {
            this.notification.add(error.data?.message || _t("The task could not be indented."), {
                type: "danger",
            });
        }
    }

    async outdentTask() {
        const task = this.selectedWbsTask;
        if (!task || !this.canOutdent || !this._guardEdit()) {
            return;
        }
        try {
            const result = await this.orm.call("project.task", "planner_wbs_outdent", [task.id]);
            if (result === false) {
                this.notification.add(_t("The task cannot be outdented here."), {
                    type: "warning",
                });
                return;
            }
            await this.loadProject(this.state.projectId);
            this.state.selectedId = task.id;
        } catch (error) {
            this.notification.add(error.data?.message || _t("The task could not be outdented."), {
                type: "danger",
            });
        }
    }

    // ---- WBS drag reorder (ordering only — never a hierarchy change) -------

    onWbsRowPointerDown(task, ev) {
        if (
            ev.button !== 0
            || this.state.renamingId
            // Ordering drag is disabled while filters or Group By are
            // active: hidden siblings would make the computed drop slot
            // meaningless and could corrupt the real sequence (BRD: never
            // produce a wrong WBS order — hierarchy/ordering stay real).
            || this.hasActiveFilters
            || this.state.groupBy
            || !this.state.canEdit
            || ev.target.closest(".o_cp_planner_add_child, .o_cp_planner_toggle, input, button, a")
        ) {
            return;
        }
        const startY = ev.clientY;
        const move = (e) => this._wbsDragMove(task, startY, e);
        const up = (e) => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            this._wbsDragEnd(task, e);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
    }

    _wbsDragMove(task, startY, ev) {
        if (!this._wbsDragActive && Math.abs(ev.clientY - startY) < 5) {
            return;
        }
        this._wbsDragActive = true;
        this.state.wbsDragId = task.id;
        // The insertion slot is computed only among VISIBLE rows that share
        // the dragged task's parent — the drop can therefore never move the
        // task into a different branch.
        const siblings = this.visibleTasks.filter((row) => row.parent_id === task.parent_id);
        const rowEls = [...this.wbsRowsRef.el.querySelectorAll(".o_cp_planner_wbs_row[data-task-id]")];
        const rowById = new Map(
            rowEls.map((el) => [Number(el.dataset.taskId), el]),
        );
        let slot = siblings.length;
        for (let i = 0; i < siblings.length; i++) {
            const el = rowById.get(siblings[i].id);
            if (!el) {
                continue;
            }
            const rect = el.getBoundingClientRect();
            if (ev.clientY < rect.top + rect.height / 2) {
                slot = i;
                break;
            }
        }
        const before = siblings[slot];
        this.state.wbsDropBeforeId = before ? before.id : null;
        this.state.wbsDropAfterId = !before && siblings.length
            ? siblings[siblings.length - 1].id
            : null;
    }

    async _wbsDragEnd(task, ev) {
        const active = this._wbsDragActive;
        const beforeId = this.state.wbsDropBeforeId;
        const afterId = this.state.wbsDropAfterId;
        this._wbsDragActive = false;
        this.state.wbsDragId = null;
        this.state.wbsDropBeforeId = null;
        this.state.wbsDropAfterId = null;
        if (!active) {
            return;
        }
        ev.preventDefault();
        // Dropped on itself or already in place — nothing to do.
        if (beforeId === task.id || afterId === task.id) {
            return;
        }
        const siblings = this.state.tasks.filter((row) => row.parent_id === task.parent_id);
        const index = siblings.findIndex((row) => row.id === task.id);
        if (
            (beforeId && siblings[index + 1]?.id === beforeId)
            || (!beforeId && afterId && siblings[index - 1]?.id === afterId)
        ) {
            return;
        }
        if (!this._guardEdit()) {
            return;
        }
        try {
            await this.orm.call("project.task", "planner_wbs_move_before", [task.id], {
                before_id: beforeId || false,
            });
            await this.loadProject(this.state.projectId);
            this.state.selectedId = task.id;
        } catch (error) {
            this.notification.add(error.data?.message || _t("The task could not be reordered."), {
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
        const slack = task.critical_slack || 0;
        if (this.isDayPrecision) {
            // Day-precision projects show slack in calendar days — the
            // stored float stays in allocated hours (BRD §17).
            const days = Math.round((slack / (this.state.hoursPerDay || 8)) * 10) / 10;
            return `+${days}d`;
        }
        return `+${Math.round(slack * 10) / 10}h`;
    }

    // BRD Planning Precision — the project plans at day granularity: no
    // time pickers, day-quantized drags, day-based duration/lag display.
    get isDayPrecision() {
        return this.state.planningPrecision === "day";
    }

    // Compact lag label used on dependency edges and inspector chips —
    // day-precision projects always express lag in days (BRD §14).
    lagText(lag, unit) {
        if (!lag) {
            return "";
        }
        const sign = lag > 0 ? "+" : "";
        if (this.isDayPrecision && unit !== "days") {
            const days = Math.round((lag / (this.state.hoursPerDay || 8)) * 10) / 10;
            return `${sign}${days}d`;
        }
        return `${sign}${lag}${unit === "days" ? "d" : "h"}`;
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
        if (!this._guardEdit()) {
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
        const rowIdx = this.rowIndexById.get(task.id) ?? 0;
        if (this.state.scale === "day" && !this.isDayPrecision) {
            // Day scale drags at hour precision — the px delta converts
            // through the folded map so compressed off-time doesn't shift
            // the landed datetime.
            const baseStart = task.dt_start
                ? parseDt(task.dt_start)
                : new Date(parseDay(task.date_start).getTime() + 9 * 3600000);
            const baseStop = task.dt_stop
                ? parseDt(task.dt_stop)
                : new Date(parseDay(task.date_stop).getTime() + 18 * 3600000);
            const x0 = this.timeToX(baseStart.getTime());
            const deltaH = Math.round(
                (this.xToTime(x0 + dx) - baseStart.getTime()) / 3600000,
            );
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
        // Day-quantized drag/resize — each edge converts px→datetime
        // through the folded map, then snaps to the containing day.
        const startMs0 = parseDay(task.date_start).getTime();
        const stopMs0 = parseDay(task.date_stop).getTime();
        let start = parseDay(task.date_start);
        let stop = parseDay(task.date_stop);
        if (dragging.mode === "move") {
            const delta = dayDiff(
                start,
                new Date(startOfDayMs(this.xToTime(this.timeToX(startMs0) + dx))),
            );
            start = addDays(start, delta);
            stop = addDays(stop, delta);
        } else if (dragging.mode === "left") {
            start = new Date(startOfDayMs(this.xToTime(this.timeToX(startMs0) + dx)));
            if (start > stop) {
                start = stop;
            }
        } else {
            // The right edge is the start of the day after stop.
            stop = new Date(
                startOfDayMs(this.xToTime(this.timeToX(stopMs0 + DAY_MS) + dx) - 1),
            );
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
        if (!this._guardEdit()) {
            return;
        }
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
        if (!this._guardEdit()) {
            return;
        }
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
        if (!label || !this._guardEdit()) {
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
        const idx = this.rowIndexById.get(task.id) ?? 0;
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
        return 280 + (this.state.showStartCol ? 88 : 0) + (this.state.showFinishCol ? 88 : 0);
    }

    formatColDate(str) {
        if (!str) {
            return "–";
        }
        return getCalendarFormats().compactDate.format(parseDay(str));
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
        // Finish-variance flags flip inward at the viewport edges — the
        // reactive scrollLeft keeps that decision current while panning.
        if (scrollEl && this.state.scrollLeft !== scrollEl.scrollLeft) {
            this.state.scrollLeft = scrollEl.scrollLeft;
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
    // Group By options: resource-backed choices (Role / Resource Type) only
    // exist while project_resource_planning is installed.
    get groupByOptions() {
        return this.state.hasResources
            ? GROUP_BY_OPTIONS
            : GROUP_BY_OPTIONS.filter((opt) => !RESOURCE_GROUP_KEYS.has(opt.key));
    }
}

registry.category("actions").add("project_critical_path.planner_workspace", PlannerWorkspace);

// Shared helpers consumed by project_resource_planning's planner patch.
export {
    DAY_MS, PLANNER_ROW_H, addDays, dayDiff, dayLabel, fmtDt,
    getCalendarFormats, isoDay, isoWeek, pad2, parseDay, parseDt,
    startOfMonth, startOfWeek,
};
