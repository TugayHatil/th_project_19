/** @odoo-module */

import { registry } from "@web/core/registry";

const PROJECT_NAME = "Planner Cert Tour Project";

function selectProject() {
    const select = document.querySelector(".o_cp_planner_workspace select");
    if (!select) {
        throw new Error("Planner project selector not rendered");
    }
    const option = [...select.options].find(
        (o) => o.textContent.trim() === PROJECT_NAME
    );
    if (!option) {
        throw new Error(`project option not found: ${PROJECT_NAME}`);
    }
    select.value = option.value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
}

function assertDayContinuity() {
    const groups = document.querySelectorAll(".o_cp_planner_gantt_group").length;
    const cols = document.querySelectorAll(".o_cp_planner_gantt_col").length;
    if (groups < 2) {
        throw new Error(`continuous timeline: expected multiple day groups, got ${groups}`);
    }
    if (cols < 48) {
        throw new Error(`day continuity: expected >48 hour columns, got ${cols}`);
    }
}

function assertTimelineLayers() {
    if (!document.querySelector(".o_cp_planner_deps path")) {
        throw new Error("dependency arrows missing");
    }
    if (!document.querySelector(".o_cp_planner_today")) {
        throw new Error("today marker missing");
    }
}

function assertScaleGroups(pattern, label) {
    return function () {
        const labels = [...document.querySelectorAll(".o_cp_planner_gantt_group")].map(
            (g) => g.textContent
        );
        if (!labels.length || !labels.some((l) => pattern.test(l))) {
            throw new Error(`${label} scale: unexpected group labels ${labels.slice(0, 3)}`);
        }
    };
}

registry.category("web_tour.tours").add("planner_workspace_certification", {
    steps: () => [
        {
            trigger: ".o_cp_planner_workspace",
            run: selectProject,
        },
        // Tasks render as bars once the project data lands.
        { trigger: ".o_cp_planner_gantt_scroll .o_cp_planner_bar" },
        // Continuous day timeline: multiple day groups, hour columns.
        { trigger: ".o_cp_planner_gantt_scroll", run: assertDayContinuity },
        // WBS row click opens the Quick Inspector.
        { trigger: ".o_cp_planner_wbs_row .o_cp_planner_task_name", run: "click" },
        { trigger: ".o_cp_planner_inspector" },
        // Dependency arrows + today marker share the timeline coordinates.
        { trigger: ".o_cp_planner_toolbar", run: assertTimelineLayers },
        // Week scale renders ISO week groups.
        { trigger: ".o_cp_planner_toolbar button:contains('Week')", run: "click" },
        { trigger: ".o_cp_planner_gantt_group", run: assertScaleGroups(/week/i, "week") },
        // Month scale renders month groups.
        { trigger: ".o_cp_planner_toolbar button:contains('Month')", run: "click" },
        { trigger: ".o_cp_planner_gantt_group", run: assertScaleGroups(/[a-z]/i, "month") },
        // Back to Day — hour columns return.
        { trigger: ".o_cp_planner_toolbar button:contains('Day')", run: "click" },
        { trigger: ".o_cp_planner_gantt_col", run: assertDayContinuity },
    ],
});
