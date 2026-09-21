import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import {
    DAY_MS, PLANNER_ROW_H, addDays, dayDiff, dayLabel, fmtDt,
    getCalendarFormats, isoDay, isoWeek, pad2, parseDay, parseDt,
    startOfMonth, startOfWeek,
} from "@project_critical_path/planner/planner_workspace";
import { PlannerWorkspace } from "@project_critical_path/planner/planner_workspace";

// Resource Planning workspace (BRD-21/23/24) + Resource Board (BRD-19) +
// the Material Plan toolbar hop — patched onto the core Planner so the
// addon stays strictly optional. The matching DOM blocks in the core
// template are gated behind state.hasResources / state.boardMode.
patch(PlannerWorkspace.prototype, {
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
    },

    closeResourceWorkspace() {
        this.state.resModalOpen = false;
    },

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
    },

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
    },

    get resSelectedReq() {
        return (this.state.resData?.requirements || []).find(
            (req) => req.id === this.state.resSelReqId,
        ) || null;
    },

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
    },

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
    },

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
    },

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
    },

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
    },

    resCandidateKey(opt) {
        return opt.employee_id ? `e${opt.employee_id}` : `q${opt.equipment_id}`;
    },

    resStars(opt) {
        return Array.from({ length: opt.priority || 0 }, (_, i) => i);
    },

    resAvatarUrl(opt) {
        return opt.employee_id ? `/web/image/hr.employee/${opt.employee_id}/avatar_128` : "";
    },

    get resSelectedOption() {
        return this.state.resOptions.find(
            (opt) => this.resCandidateKey(opt) === this.state.resSelOptKey,
        ) || null;
    },

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
    },

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
    },

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
    },

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
    },

    resStatusLabel(req) {
        return {
            waiting: _t("Pending"),
            partial: _t("Partial"),
            assigned: _t("Assigned"),
        }[req.status] || "—";
    },

    resStatusClass(req) {
        return {
            waiting: "text-bg-danger",
            partial: "text-bg-warning",
            assigned: "text-bg-success",
        }[req.status] || "text-bg-secondary";
    },

    resAvailabilityLabel(opt) {
        return {
            fully_available: _t("Fully available"),
            partially_available: _t("Partially occupied"),
            unavailable: _t("Conflict"),
        }[opt.availability] || "—";
    },

    resAvailabilityDot(opt) {
        return {
            fully_available: "o_cp_res_dot_ok",
            partially_available: "o_cp_res_dot_warn",
            unavailable: "o_cp_res_dot_conflict",
        }[opt.availability] || "";
    },

    // ---- Candidate timeline (BRD-22) ---------------------------------------
    // Same scale semantics as the Resource Board: day = 24 hour columns,
    // week = 7 day columns, month = the anchor's calendar month. Anchored
    // on the requirement by default and shifted by ‹ › navigation.

    resTlUnitMs() {
        return { day: 3600000, week: DAY_MS, month: DAY_MS }[this.state.resTlScale];
    },

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
    },

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
    },

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
    },

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
    },

    async resTlToday() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        this.state.resTlAnchor = this.state.resTlScale === "month" ? startOfMonth(today)
            : this.state.resTlScale === "week" ? startOfWeek(today) : today;
        await this.loadResOptions(this.state.resSelReqId);
    },

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
    },

    get resTlPickerValue() {
        const range = this.resTlRange;
        return range ? isoDay(range.start) : "";
    },

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
    },

    resTlItemMs(item) {
        return {
            s: item.dt_start ? parseDt(item.dt_start).getTime()
                : parseDay(item.date_start).getTime() + 9 * 3600000,
            e: item.dt_end ? parseDt(item.dt_end).getTime()
                : parseDay(item.date_end).getTime() + 18 * 3600000,
        };
    },

    resTlMsToStyle(s, e) {
        const range = this.resTlRange;
        if (!range) {
            return "display:none";
        }
        const span = range.end.getTime() - range.start.getTime();
        const left = Math.max((s - range.start.getTime()) / span * 100, 0);
        const width = Math.min((e - s) / span * 100, 100 - left);
        return `left:${left}%;width:${Math.max(width, 1)}%`;
    },

    resTlItemStyle(item) {
        const drag = this.state.resTlDrag;
        if (drag && drag.itemId === item.id) {
            return this.resTlMsToStyle(drag.startMs, drag.endMs);
        }
        const { s, e } = this.resTlItemMs(item);
        return this.resTlMsToStyle(s, e);
    },

    resTlItemClass(item) {
        return {
            mine: item.mine,
            conflict: item.overlaps && !item.mine,
            dragging: this.state.resTlDrag?.itemId === item.id,
        };
    },

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
    },

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
    },

    resTlDragStyle() {
        const drag = this.state.resTlDrag;
        if (!drag) {
            return "display:none";
        }
        return this.resTlMsToStyle(drag.startMs, drag.endMs);
    },

    resTlDragClass() {
        const drag = this.state.resTlDrag;
        return {
            conflict: drag?.conflict,
            outside: drag?.outside,
        };
    },

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
    },

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
    },

    resTlPendingClass() {
        const pend = this.state.resTlPending;
        return {
            conflict: pend?.conflict,
            outside: pend?.outside,
        };
    },

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
    },

    resTlPendingDurationText() {
        const pend = this.state.resTlPending;
        if (!pend) {
            return "";
        }
        const hrs = pend.estHours ?? (pend.endMs - pend.startMs) / 3600000;
        return `${this.formatHours(hrs)} ${_t("planned")}`;
    },

    resTlPendingSet(s, e) {
        const pend = this.state.resTlPending;
        if (!pend) {
            return;
        }
        pend.startMs = Math.min(s, e);
        pend.endMs = Math.max(s, e);
        pend.conflict = this.resTlConflict(pend.startMs, pend.endMs);
        pend.outside = this.resTlOutside(pend.startMs, pend.endMs);
    },

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
    },

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
    },

    cancelResTlPending() {
        this.state.resTlPending = null;
    },

    // ---- Existing assignment actions (BRD-24) ------------------------------
    // Clicking a bar selects it and opens the detail card; only assignments
    // of the selected requirement ("mine") can be edited or deleted — other
    // bars belong to different tasks/requirements and are view-only.

    selectResAssignment(item) {
        this.state.resSelAssignId =
            this.state.resSelAssignId === item.id ? null : item.id;
        this.state.resAssignEdit = null;
        this.state.resAssignDelConfirm = false;
    },

    get resSelectedAssignment() {
        const opt = this.resSelectedOption;
        if (!opt || !this.state.resSelAssignId) {
            return null;
        }
        return (opt.schedule || []).find(
            (item) => item.id === this.state.resSelAssignId
        ) || null;
    },

    resAssignTypeLabel() {
        const opt = this.resSelectedOption;
        if (!opt) {
            return "";
        }
        return opt.employee_id ? _t("Person") : _t("Equipment");
    },

    resAssignDurationText(item) {
        const hrs = item.planned_hours
            ?? (this.resTlItemMs(item).e - this.resTlItemMs(item).s) / 3600000;
        return `${this.formatHours(hrs)} ${_t("planned")}`;
    },

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
    },

    cancelResAssignEdit() {
        this.state.resAssignEdit = null;
    },

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
    },

    askDeleteResAssignment() {
        if (this.resSelectedAssignment?.mine) {
            this.state.resAssignDelConfirm = true;
            this.state.resAssignEdit = null;
        }
    },

    cancelDeleteResAssignment() {
        this.state.resAssignDelConfirm = false;
    },

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
    },

    // ---- Timeline dragging -------------------------------------------------

    resTlPointMs(clientX, rect) {
        const range = this.resTlRange;
        const ratio = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
        return range.start.getTime() + ratio * (range.end.getTime() - range.start.getTime());
    },

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
    },

    resTlConflict(s, e, excludeId) {
        return (this.resSelectedOption?.schedule || []).some(
            (item) => item.id !== excludeId && this.resTlItemMs(item).s < e && this.resTlItemMs(item).e > s,
        );
    },

    resTlOutside(s, e) {
        const req = this.state.resRequired;
        if (!req?.start_dt || !req?.end_dt) {
            return false;
        }
        return s < parseDt(req.start_dt).getTime() || e > parseDt(req.end_dt).getTime();
    },

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
    },

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
    },

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
    },

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
    },

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
    },

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
    },

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
    },

    gripStyle(task, side) {
        const bar = this.barGeometry(task);
        if (!bar) {
            return "display:none";
        }
        const width = Math.min(8, bar.width);
        const left = side === "left" ? bar.left - 2 : bar.left + bar.width - width + 2;
        return `left:${left}px;width:${width}px`;
    },

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
    },

    // Clicking empty space (below/beside the task rows) clears the current
    // row selection; clicks inside a row or the inspector are ignored.
    onBackgroundClick(ev) {
        if (ev.target.closest(".o_cp_planner_wbs_row, .o_cp_planner_gantt_row, .o_cp_planner_dep_edit")) {
            return;
        }
        this.state.selectedId = null;
        this.state.inspectorOpen = false;
        this.state.depEdit = null;
    },

    onRowClick(task) {
        if (this.suppressClick) {
            this.suppressClick = false;
            return;
        }
        this.selectTask(task);
    },

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
    },

    onWbsScroll() {
        const scrollEl = this.ganttScrollRef.el;
        const wbsEl = this.wbsRowsRef.el;
        if (scrollEl && wbsEl && scrollEl.scrollTop !== wbsEl.scrollTop) {
            scrollEl.scrollTop = wbsEl.scrollTop;
        }
    },

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
    },

    setBoardMode(on) {
        this.state.boardMode = on;
        if (on && this.state.projectId) {
            this.loadBoard();
        } else if (!on) {
            this._pendingFit = true;
        }
    },

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
    },

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
    },

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
    },

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
    },

    boardMsToStyle(s, e) {
        const range = this.boardRange;
        if (!range) {
            return "display:none";
        }
        const span = range.end.getTime() - range.start.getTime();
        const left = Math.max((s - range.start.getTime()) / span * 100, 0);
        const width = Math.min((e - s) / span * 100, 100 - left);
        return `left:${left}%;width:${Math.max(width, 0.5)}%`;
    },

    boardItemStyle(item) {
        const { s, e } = this.resTlItemMs(item);
        return this.boardMsToStyle(s, e);
    },

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
    },

    onBoardBarLeave() {
        this.state.boardTip = null;
    },

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
    },

    boardTipDuration(item) {
        return `${_t("Duration")}: ${this.formatHours(item.planned_hours)}`;
    },

    boardTipStatus(item) {
        return `${_t("Status")}: ${item.task_state}`;
    },

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
    },

    get boardPersonnel() {
        return this.state.boardResources.filter((res) => res.category === "human");
    },

    get boardEquipment() {
        return this.state.boardResources.filter((res) => res.category === "equipment");
    },

    boardGroupCollapsed(key) {
        return this.state.boardGroupsCollapsed.has(key);
    },

    toggleBoardGroup(key) {
        const next = new Set(this.state.boardGroupsCollapsed);
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        this.state.boardGroupsCollapsed = next;
    },

    selectBoardResource(res) {
        this.state.boardSelKey = this.state.boardSelKey === res.key ? null : res.key;
    },



    async boardNavigate(dir) {
        const base = this.boardAnchorDate();
        if (this.state.boardScale === "month") {
            this.state.boardAnchor = new Date(base.getFullYear(), base.getMonth() + dir, 1);
        } else {
            this.state.boardAnchor = addDays(base, dir * (this.state.boardScale === "week" ? 7 : 1));
        }
        await this.loadBoard();
    },

    async boardToday() {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        this.state.boardAnchor = this.state.boardScale === "month" ? startOfMonth(d)
            : this.state.boardScale === "week" ? startOfWeek(d) : d;
        await this.loadBoard();
    },

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
    },

    get boardPickerValue() {
        return isoDay(this.boardAnchorDate());
    },

    async onBoardDatePick(ev) {
        const val = ev.target.value;
        if (!val) {
            return;
        }
        const picked = parseDay(val);
        this.state.boardAnchor = this.state.boardScale === "month" ? startOfMonth(picked)
            : this.state.boardScale === "week" ? startOfWeek(picked) : picked;
        await this.loadBoard();
    },


    // Material Plan (BRD): quick hop from the Planner toolbar to the
    // project-scoped material list — same project context, standard
    // list/form views, Filters & Group By come from the search view.
    openMaterialPlan() {
        if (!this.state.projectId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Material Plan"),
            res_model: "project.material.plan",
            views: [[false, "list"], [false, "form"]],
            domain: [["project_id", "=", this.state.projectId]],
            context: { default_project_id: this.state.projectId },
            target: "current",
        });
    },

});
