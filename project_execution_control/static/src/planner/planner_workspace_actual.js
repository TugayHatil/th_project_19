/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import {
    PlannerWorkspace, fmtDt, isoDay, parseDay, dayLabel,
} from "@project_critical_path/planner/planner_workspace";

// Actual tracking (Execution & Control BRD §4/§26): renders a third,
// thin "actual" bar inside the existing planner row — baseline ghost and
// plan bar are untouched. No actual data → no bar. An open-ended actual
// (start entered, still running) stretches to "now" with a dashed look.
const VARIANCE_LABEL = {
    late: _t("Completed Late"),
    early: _t("Completed Early"),
    on_time: _t("Completed On Time"),
};
const STATUS_LABEL = {
    not_started: _t("Not Started"),
    in_progress: _t("In Progress"),
    done: _t("Done"),
};
const MATERIAL_RISK_LABEL = {
    partial: _t("Partial Availability"),
    delayed: _t("Material Delay"),
    critical: _t("Critical Material Delay"),
};

patch(PlannerWorkspace.prototype, {

    // Day+datetime pair the actual bar is drawn with. A running actual
    // has no finish yet — the bar provisionally ends at "now".
    actualBarStyle(task) {
        if (!task.actual_start) {
            return "display:none";
        }
        const now = new Date();
        const stopStr = task.actual_end || isoDay(now);
        const stopDt = task.dt_actual_end || fmtDt(now);
        const bar = this.spanGeometry(
            task.actual_start, stopStr, task.dt_actual_start, stopDt,
        );
        if (!bar) {
            return "display:none";
        }
        return `left:${bar.left}px;width:${bar.width}px`;
    },

    actualBarClass(task) {
        if (task.actual_status === "in_progress") {
            return "in_progress";
        }
        return task.schedule_variance_state || "";
    },

    actualBarTooltip(task) {
        const start = task.actual_start
            ? dayLabel(parseDay(task.actual_start)) : "–";
        const end = task.actual_end
            ? dayLabel(parseDay(task.actual_end)) : _t("now");
        const lines = [
            `${_t("Actual")}: ${start} – ${end}`,
            STATUS_LABEL[task.actual_status] || "",
        ];
        if (task.actual_duration) {
            lines.push(`${_t("Actual Duration")}: ${Math.round(task.actual_duration * 100) / 100}h`);
        }
        if (task.schedule_variance_state) {
            const days = task.schedule_variance_days;
            const suffix = days ? ` (${days > 0 ? "+" : ""}${days}d)` : "";
            lines.push(`${VARIANCE_LABEL[task.schedule_variance_state] || ""}${suffix}`);
        }
        return lines.filter(Boolean).join("\n");
    },

    // Material-risk dot tooltip (BRD §6.4): the badge itself stays a
    // coloured dot; the numbers live in the title so a risky row never
    // needs the inspector open.
    materialRiskTooltip(task) {
        const risk = task.material_risk;
        const lines = [
            `${_t("Material Risk")}: ${MATERIAL_RISK_LABEL[risk] || risk || ""}`,
        ];
        if (task.material_delay_days) {
            lines.push(`${_t("Material Delay")}: ${task.material_delay_days}d`);
        }
        if (task.material_shortage_quantity) {
            lines.push(`${_t("Shortage")}: ${task.material_shortage_quantity}`);
        }
        if (task.material_downstream_count) {
            lines.push(`${_t("Downstream Tasks Affected")}: ${task.material_downstream_count}`);
        }
        if (task.material_project_impact_days) {
            lines.push(`${_t("Project Finish Impact")}: +${task.material_project_impact_days}d`);
        }
        if (task.material_risk_detail) {
            lines.push(task.material_risk_detail);
        }
        return lines.filter(Boolean).join("\n");
    },
});
