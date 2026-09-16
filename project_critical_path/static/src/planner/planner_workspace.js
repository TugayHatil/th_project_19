import { Component, onMounted, useExternalListener, useRef, useState } from "@odoo/owl";
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
        };
    }
    return calendarFormats;
}
const monthLabel = (date) => getCalendarFormats().monthYear.format(date);
const dayLabel = (date) => getCalendarFormats().dayMonth.format(date);
const isoDay = (date) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
const resIsoWeek = (date) => {
    const d = new Date(date);
    d.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7));
    const week1 = new Date(d.getFullYear(), 0, 4);
    return 1 + Math.round(((d - week1) / DAY_MS + ((week1.getDay() + 6) % 7)) / 7);
};

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
            rangeStart: new Date(),
            rangeEnd: new Date(),
            // Quick Inspector panel
            inspectorOpen: false,
            inspectorLoading: false,
            inspector: null,
            baseline: null,
            impact: null,
            depOpen: false,
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
            // Optional WBS date columns (BRD-19) — hidden by default
            colMenuOpen: false,
            showStartCol: false,
            showFinishCol: false,
            // Bar info field selector (BRD-17) — per-project selection
            barInfoOpen: false,
            barInfoKeys: [...BAR_INFO_DEFAULT],
            // Slack chip pinned left of each bar (BRD-18) — per-project toggle
            slackVisible: true,
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
            resTlScale: "day",
            resTlAnchor: null,
            resTlDrag: null,
            resTlPending: null,
            // Selected existing assignment + its edit/delete sub-state (BRD-24)
            resSelAssignId: null,
            resAssignEdit: null,
            resAssignDelConfirm: false,
        });
        this.scales = SCALES;
        this.barInfoFields = BAR_INFO_FIELDS;
        this.resTlScales = { hour: _t("Hour"), day: _t("Day"), week: _t("Week") };
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
        onMounted(async () => {
            try {
                this.state.projects = await this.orm.call("project.project", "get_planner_projects", []);
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
            const kwargs = this.state.compareBaselineId
                ? { baseline_id: this.state.compareBaselineId }
                : {};
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
        if (!dates.length) {
            this.state.rangeStart = addDays(today, -7);
            this.state.rangeEnd = addDays(today, 21);
            return;
        }
        let start = dates[0];
        let end = dates[0];
        for (const date of dates) {
            if (date < start) {
                start = date;
            }
            if (date > end) {
                end = date;
            }
        }
        this.state.rangeStart = addDays(start, -3);
        this.state.rangeEnd = addDays(end, 3);
    }

    // Origin shared by columns, bars and the today marker so they stay aligned
    // when the scale snaps column boundaries to week/month starts.
    get origin() {
        const { rangeStart, scale } = this.state;
        if (scale === "week") {
            return startOfWeek(rangeStart);
        }
        if (scale === "month") {
            return startOfMonth(rangeStart);
        }
        return rangeStart;
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

    get columns() {
        const cols = [];
        const { rangeEnd, scale } = this.state;
        const origin = this.origin;
        if (scale === "day") {
            for (let day = origin; day <= rangeEnd; day = addDays(day, 1)) {
                cols.push({ start: day, days: 1, label: pad2(day.getDate()), group: monthLabel(day) });
            }
        } else if (scale === "week") {
            for (let day = origin; day <= rangeEnd; day = addDays(day, 7)) {
                cols.push({ start: day, days: 7, label: dayLabel(day), group: monthLabel(day) });
            }
        } else {
            for (let day = origin; day <= rangeEnd; day = new Date(day.getFullYear(), day.getMonth() + 1, 1)) {
                const next = new Date(day.getFullYear(), day.getMonth() + 1, 1);
                cols.push({ start: day, days: dayDiff(day, next), label: monthLabel(day), group: String(day.getFullYear()) });
            }
        }
        return cols;
    }

    get columnGroups() {
        const groups = [];
        for (const col of this.columns) {
            const last = groups[groups.length - 1];
            if (last && last.label === col.group) {
                last.width += col.days * this.state.pxPerDay;
            } else {
                groups.push({ label: col.group, width: col.days * this.state.pxPerDay });
            }
        }
        return groups;
    }

    get timelineWidth() {
        return Math.max(dayDiff(this.origin, this.state.rangeEnd) * this.state.pxPerDay, 1);
    }

    get todayLeft() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        return dayDiff(this.origin, today) * this.state.pxPerDay;
    }

    spanGeometry(startStr, stopStr) {
        if (!startStr || !stopStr) {
            return false;
        }
        const start = parseDay(startStr);
        const stop = parseDay(stopStr);
        return {
            left: dayDiff(this.origin, start) * this.state.pxPerDay,
            width: Math.max(dayDiff(start, stop) + 1, 1) * this.state.pxPerDay,
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

    barTitle(task) {
        return task.is_critical ? `${task.name} — ${_t("Critical Path")}` : task.name;
    }

    resRoleLabel(role) {
        return role.category === "equipment"
            ? `${role.name} (${_t("Equipment")})`
            : role.name;
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
        return this.spanGeometry(dates.start, dates.stop);
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
        if (!dates.start || !dates.stop || !task.baseline_stop) {
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
            for (const predId of task.depend_on_ids || []) {
                const predIdx = indexById.get(predId);
                if (predIdx === undefined) {
                    continue; // predecessor collapsed or outside this project
                }
                const fromBar = this.barGeometry(byId.get(predId));
                if (!fromBar) {
                    continue;
                }
                raw.push({ predId, task, predIdx, toIdx: indexById.get(task.id), fromBar, toBar });
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
            return {
                key: `${edge.predId}-${edge.task.id}`,
                d,
                arrowD: `M ${x2} ${y2} l -8 -4.5 l 0 9 z`,
                dim: Boolean(selected && !related),
                highlight: Boolean(selected && related),
                critical: Boolean(edge.task.is_critical && byId.get(edge.predId)?.is_critical),
            };
        });
    }

    setScale(scale) {
        this.state.scale = scale;
        // Refit instead of the fixed pxPerDay — the scale buttons only
        // change column granularity, the timeline always fills the viewport.
        this.fit();
    }

    goToday() {
        const el = this.ganttScrollRef.el;
        if (!el) {
            return;
        }
        el.scrollLeft = Math.max(this.todayLeft - el.clientWidth / 3, 0);
    }

    fit() {
        const el = this.ganttScrollRef.el;
        if (!el) {
            return;
        }
        const days = Math.max(dayDiff(this.origin, this.state.rangeEnd), 1);
        this.state.pxPerDay = Math.min(Math.max((el.clientWidth - 4) / days, 0.25), 200);
        el.scrollLeft = 0;
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
            const t = detail.task;
            this.state.form = {
                name: t.name,
                date_start: t.date_start || "",
                date_stop: t.date_stop || "",
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

    async saveInspector() {
        const form = this.state.form;
        const taskId = this.state.inspector?.id;
        if (!taskId || !form) {
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.call("project.task", "update_planner_task", [taskId], {
                values: {
                    name: form.name,
                    date_start: form.date_start || false,
                    date_stop: form.date_stop || false,
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
            this.state.selectedId = taskId;
            await this.loadInspector(taskId);
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
        ev.preventDefault();
        ev.stopPropagation();
        this.dragging = {
            task,
            mode,
            startX: ev.clientX,
            moved: false,
        };
        const onMove = (e) => this.onDragMove(e);
        const onUp = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            window.removeEventListener("pointercancel", onUp);
            this.onDragEnd();
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onUp);
    }

    onDragMove(ev) {
        const dragging = this.dragging;
        if (!dragging) {
            return;
        }
        const dx = ev.clientX - dragging.startX;
        if (!dragging.moved && Math.abs(dx) < 4) {
            return; // click threshold — avoids accidental micro-drags
        }
        dragging.moved = true;
        const delta = Math.round(dx / this.state.pxPerDay);
        const task = dragging.task;
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
        const rowIdx = this.visibleTasks.findIndex((row) => row.id === task.id);
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
        this.persistTaskDates(dragging.task, drag.start, drag.stop);
    }

    async persistTaskDates(task, start, stop) {
        try {
            await this.orm.call("project.task", "update_planner_task", [task.id], {
                values: {
                    date_start: start,
                    date_stop: stop,
                    duration_days: dayDiff(parseDay(start), parseDay(stop)) + 1,
                },
            });
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

    resTooltip(task) {
        const names = task.resources?.names || [];
        return names.length ? names.join("\n") : _t("Manage resources");
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
    // Continuous time axis at hour/day/week granularity. All bookings arrive
    // with the options RPC; drags only write once on pointer-up.

    resTlUnitMs() {
        return { hour: 3600000, day: DAY_MS, week: 7 * DAY_MS }[this.state.resTlScale];
    }

    // Visible range per scale; anchored on the requirement by default and
    // shifted by ‹ › navigation.
    get resTlRange() {
        const req = this.resSelectedReq;
        if (!req?.date_start || !req?.date_end) {
            return false;
        }
        const reqStart = parseDay(req.date_start);
        const reqEnd = parseDay(req.date_end);
        const anchor = this.state.resTlAnchor;
        if (this.state.resTlScale === "hour") {
            const start = anchor || reqStart;
            return { start, end: addDays(start, 1) };
        }
        if (this.state.resTlScale === "week") {
            const start = anchor || addDays(startOfWeek(reqStart), -7);
            const weeks = Math.ceil(Math.max(dayDiff(reqStart, reqEnd) + 1, 1) / 7) + 2;
            return { start, end: addDays(start, weeks * 7) };
        }
        const start = anchor || addDays(reqStart, -2);
        return { start, end: addDays(start, dayDiff(reqStart, reqEnd) + 5) };
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
            if (this.state.resTlScale === "hour") {
                cols.push({ label: pad2(d.getHours()) });
            } else if (this.state.resTlScale === "week") {
                cols.push({ label: `${_t("Week")} ${resIsoWeek(d)}` });
            } else {
                cols.push({ label: pad2(d.getDate()) });
            }
        }
        return cols;
    }

    async resTlNavigate(dir) {
        const range = this.resTlRange;
        if (!range) {
            return;
        }
        // Hour view shows one day → navigate by day; week view by week;
        // day view jumps a full visible span.
        const step = {
            hour: DAY_MS,
            week: 7 * DAY_MS,
        }[this.state.resTlScale] || (range.end.getTime() - range.start.getTime());
        this.state.resTlAnchor = new Date(range.start.getTime() + dir * step);
        await this.loadResOptions(this.state.resSelReqId);
    }

    async resTlToday() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        this.state.resTlAnchor = this.state.resTlScale === "week"
            ? startOfWeek(today)
            : today;
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
        this.state.resTlAnchor = scale === "week"
            ? startOfWeek(cur)
            : new Date(cur.getFullYear(), cur.getMonth(), cur.getDate());
        await this.loadResOptions(this.state.resSelReqId);
    }

    get resTlPickerValue() {
        const range = this.resTlRange;
        return range ? isoDay(range.start) : "";
    }

    // Direct date jump: hour view opens that day, day view centers the
    // picked date inside the span, week view opens its week (BRD-23 §7).
    async onResTlDatePick(ev) {
        const val = ev.target.value;
        if (!val) {
            return;
        }
        const picked = parseDay(val);
        if (this.state.resTlScale === "week") {
            this.state.resTlAnchor = startOfWeek(picked);
        } else if (this.state.resTlScale === "day") {
            const range = this.resTlRange;
            const span = range ? dayDiff(range.start, range.end) : 7;
            this.state.resTlAnchor = addDays(picked, -Math.floor(span / 2));
        } else {
            this.state.resTlAnchor = picked;
        }
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

    // Snap a timestamp to the scale unit: hour boundaries, 09:00/18:00 day
    // edges (the existing assignment defaults), Mon 09:00 / Sun 18:00 weeks.
    resTlSnap(ms, edge) {
        const d = new Date(ms);
        if (this.state.resTlScale === "hour") {
            d.setMinutes(0, 0, 0);
            return edge === "end" ? d.getTime() + 3600000 : d.getTime();
        }
        if (this.state.resTlScale === "week") {
            const monday = startOfWeek(d);
            return edge === "end"
                ? addDays(monday, 6).getTime() + 18 * 3600000
                : monday.getTime() + 9 * 3600000;
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
        const bar = this.spanGeometry(drag.start, drag.stop);
        const start = parseDay(drag.start);
        const stop = parseDay(drag.stop);
        return {
            style: `left:${bar.left}px;top:${Math.max(drag.rowIdx * PLANNER_ROW_H - 22, 0)}px`,
            text: `${dayLabel(start)} – ${dayLabel(stop)} · ${dayDiff(start, stop) + 1}d`,
        };
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
    }

    onWbsScroll() {
        const scrollEl = this.ganttScrollRef.el;
        const wbsEl = this.wbsRowsRef.el;
        if (scrollEl && wbsEl && scrollEl.scrollTop !== wbsEl.scrollTop) {
            scrollEl.scrollTop = wbsEl.scrollTop;
        }
    }

    async onProjectChange(ev) {
        this.state.projectId = Number(ev.target.value) || false;
        if (this.state.projectId) {
            await this.loadProject(this.state.projectId);
            // A different project means a different range — refit it.
            this.fit();
        }
    }
}

registry.category("actions").add("project_critical_path.planner_workspace", PlannerWorkspace);
