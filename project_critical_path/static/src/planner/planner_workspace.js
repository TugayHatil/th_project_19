import { Component, onMounted, useExternalListener, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

const DAY_MS = 86400000;
const SCALES = {
    day: { pxPerDay: 36, label: _t("Day") },
    week: { pxPerDay: 6, label: _t("Week") },
    month: { pxPerDay: 1.6, label: _t("Month") },
};

const parseDay = (str) => {
    const [y, m, d] = str.split("-").map(Number);
    return new Date(y, m - 1, d);
};
const addDays = (date, days) => new Date(date.getTime() + days * DAY_MS);
const dayDiff = (a, b) => Math.round((b.getTime() - a.getTime()) / DAY_MS);
const startOfWeek = (date) => addDays(date, -((date.getDay() + 6) % 7));
const startOfMonth = (date) => new Date(date.getFullYear(), date.getMonth(), 1);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad2 = (n) => String(n).padStart(2, "0");
const monthLabel = (date) => `${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
const dayLabel = (date) => `${MONTHS[date.getMonth()]} ${pad2(date.getDate())}`;
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
        });
        this.scales = SCALES;
        useExternalListener(document.body, "keydown", (ev) => {
            if (ev.key === "Escape" && this.state.inspectorOpen) {
                this.state.inspectorOpen = false;
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
            } else {
                this.state.loading = false;
            }
        });
    }

    async loadProject(projectId) {
        this.state.loading = true;
        this.state.collapsedIds = new Set();
        this.state.selectedId = null;
        this.state.inspectorOpen = false;
        try {
            const data = await this.orm.call("project.project", "get_planner_data", [projectId]);
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

    barGeometry(task) {
        if (!task.date_start || !task.date_stop) {
            return false;
        }
        const start = parseDay(task.date_start);
        const stop = parseDay(task.date_stop);
        return {
            left: dayDiff(this.origin, start) * this.state.pxPerDay,
            width: Math.max(dayDiff(start, stop) + 1, 1) * this.state.pxPerDay,
        };
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
            const x2 = edge.toBar.left;
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
                arrowD: `M ${x2} ${y2} l -7 -4 l 0 8 z`,
                dim: Boolean(selected && !related),
                highlight: Boolean(selected && related),
                critical: Boolean(edge.task.is_critical && byId.get(edge.predId)?.is_critical),
            };
        });
    }

    setScale(scale) {
        this.state.scale = scale;
        this.state.pxPerDay = SCALES[scale].pxPerDay;
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
                duration_days: t.date_start && t.date_stop
                    ? dayDiff(parseDay(t.date_start), parseDay(t.date_stop))
                    : 0,
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
        return dayLabel(parseDay(str));
    }

    formatDayCount(days) {
        if (days === false || days === null || days === undefined || Number.isNaN(days)) {
            return "—";
        }
        return `${days}d`;
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
        if (form?.duration_days === undefined || baseline?.duration_days === false || baseline?.duration_days === undefined) {
            return false;
        }
        return form.duration_days - baseline.duration_days;
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
            form.date_stop = isoDay(addDays(parseDay(form.date_start), form.duration_days || 0));
        }
    }

    onStopChange(ev) {
        const form = this.state.form;
        form.date_stop = ev.target.value;
        if (form.date_stop && form.date_start) {
            form.duration_days = Math.max(dayDiff(parseDay(form.date_start), parseDay(form.date_stop)), 0);
        }
    }

    onDurationChange(ev) {
        const form = this.state.form;
        form.duration_days = Math.max(Number(ev.target.value) || 0, 0);
        if (form.date_start) {
            form.date_stop = isoDay(addDays(parseDay(form.date_start), form.duration_days));
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
        }
    }
}

registry.category("actions").add("project_critical_path.planner_workspace", PlannerWorkspace);
