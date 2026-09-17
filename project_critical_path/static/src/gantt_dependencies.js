import { Component, onWillRender, useEffect, useExternalListener, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { usePopover } from "@web/core/popover/popover_hook";
import { patch } from "@web/core/utils/patch";
import { GanttConnector } from "@web_gantt/gantt_connector";
import { GanttModel } from "@web_gantt/gantt_model";
import { GanttRenderer } from "@web_gantt/gantt_renderer";
import { GanttRendererControls } from "@web_gantt/gantt_renderer_controls";
import { dependencyGeometry, visualDependency } from "./gantt_dependency_geometry";

const enhanced = (model) => model.metaData.resModel === "project.task" &&
    Boolean(model.metaData.fields.gantt_dependency_metadata);
const typeNames = { FS: _t("Finish-to-Start"), SS: _t("Start-to-Start"), FF: _t("Finish-to-Finish"), SF: _t("Start-to-Finish") };
const errorMessage = (error) => error.data?.message || error.message || _t("The dependency could not be saved.");

export class DependencyDialog extends Component {
    static template = "project_critical_path.DependencyDialog";
    static components = { Dialog };
    static props = ["close", "model", "records", "sourceId?", "targetId?", "taskId?", "mode"];

    setup() {
        this.title = _t("Task Dependency");
        this.types = typeNames;
        this.records = [...new Map(this.props.records.map((record) => [record.id, record])).values()];
        const ids = new Set(this.records.map((record) => record.id));
        this.links = this.records.flatMap((target) => (target.depend_on_ids || [])
            .filter((id) => ids.has(id) && (!this.props.taskId || target.id === this.props.taskId || id === this.props.taskId))
            .map((id) => ({ source: id, target: target.id, key: `${id}:${target.id}` })));
        this.state = useState({ source: this.props.sourceId || this.props.taskId || this.records[0]?.id,
            target: this.props.targetId || this.records.find((r) => r.id !== (this.props.sourceId || this.props.taskId))?.id,
            type: "FS", lag: 0, busy: false, error: "" });
        if (this.props.mode !== "add" && !this.props.sourceId && this.links.length) {
            this.state.source = this.links[0].source;
            this.state.target = this.links[0].target;
        }
        this.loadMetadata();
    }

    name(id) {
        return this.records.find((record) => record.id === id)?.display_name || String(id);
    }

    loadMetadata() {
        const target = this.records.find((record) => record.id === this.state.target);
        const metadata = target?.gantt_dependency_metadata?.[this.state.source];
        this.state.type = metadata?.type || "FS";
        this.state.lag = metadata?.lag || 0;
    }

    selectLink(event) {
        [this.state.source, this.state.target] = event.target.value.split(":").map(Number);
        this.loadMetadata();
    }

    get canSave() {
        return !this.state.busy && this.state.source && this.state.target &&
            (this.props.mode === "add" || this.links.some((link) => link.source === this.state.source && link.target === this.state.target));
    }

    async save() {
        if (!this.canSave) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            if (this.props.mode === "remove") {
                await this.props.model.removeDependency(this.state.source, this.state.target);
            } else {
                const lag = Number(this.state.lag);
                if (!Number.isFinite(lag)) {
                    throw new Error(_t("Enter a finite number of days."));
                }
                await this.props.model.cpSaveDependency(this.state.source, this.state.target, this.state.type, lag, this.props.mode === "add");
            }
            this.props.close();
        } catch (error) {
            this.state.error = errorMessage(error);
        } finally {
            this.state.busy = false;
        }
    }
}

class DependencyMenu extends Component {
    static template = "project_critical_path.DependencyMenu";
    static props = ["open", "close"];
    choose(mode) {
        this.props.close();
        this.props.open(mode);
    }
}

patch(GanttModel.prototype, {
    async cpSaveDependency(source, target, type = "FS", lag = 0, create = false) {
        await this.mutex.exec(() => this.orm.call("project.task", "set_gantt_dependency",
            [[target], source, type, lag, create], { context: this.searchParams.context }));
        await this.fetchData();
    },
    async createDependency(source, target) {
        if (!enhanced(this)) {
            return super.createDependency(...arguments);
        }
        const type = this.cpDraftType || "FS";
        this.cpDraftType = null;
        try {
            await this.cpSaveDependency(source, target, type, 0, true);
        } catch (error) {
            this.notification.add(errorMessage(error), { type: "danger" });
        }
    },
    async removeDependency(source, target) {
        if (!enhanced(this)) {
            return super.removeDependency(...arguments);
        }
        await this.mutex.exec(() => this.orm.call("project.task", "remove_gantt_dependency",
            [[target], source], { context: this.searchParams.context }));
        await this.fetchData();
    },
});

patch(GanttRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        if (!enhanced(this.model)) {
            return;
        }
        this.cpDependencyUI = useState({ visible: true });
        this.model.cpDependencyUI = this.cpDependencyUI;
        this.cpMenu = usePopover(DependencyMenu);
        useEffect((grid) => {
            if (!grid) {
                return;
            }
            grid.classList.add("o_cp_dependency_gantt");
            const start = (event) => {
                const bullet = event.target.closest(".o_connector_creator_bullet");
                this.cpSourceEdge = null;
                this.model.cpDraftType = null;
                if (bullet && this.model.metaData.canEdit) {
                    this.cpSourceEdge = this.cpEdge(event, bullet.closest(".o_gantt_pill_wrapper"));
                }
            };
            const menu = (event) => {
                const element = event.target.closest("[data-pill-id]");
                const pill = this.pills[element?.dataset.pillId];
                if (!pill || !this.model.metaData.canEdit || !this.shouldRenderRecordConnectors(pill.record)) {
                    return;
                }
                event.preventDefault();
                this.cpMenu.open(element, { close: () => this.cpMenu.close(), open: (mode) => this.cpOpenDialog(mode, { taskId: pill.record.id }) });
            };
            grid.addEventListener("pointerdown", start, true);
            grid.addEventListener("contextmenu", menu);
            return () => {
                grid.removeEventListener("pointerdown", start, true);
                grid.removeEventListener("contextmenu", menu);
            };
        }, () => [this.gridRef.el]);
        useExternalListener(window, "pointerup", (event) => {
            const element = document.elementFromPoint(event.clientX, event.clientY)?.closest("[data-pill-id]");
            if (this.cpSourceEdge && element && this.gridRef.el?.contains(element)) {
                this.model.cpDraftType = this.cpSourceEdge + this.cpEdge(event, element);
            }
            this.cpSourceEdge = null;
        }, { capture: true });
        useExternalListener(window, "pointercancel", () => {
            this.cpSourceEdge = null;
            this.model.cpDraftType = null;
        });
    },
    cpEdge(event, element) {
        const bounds = element.getBoundingClientRect();
        const left = event.clientX < bounds.left + bounds.width / 2;
        return left !== (localization.direction === "rtl") ? "S" : "F";
    },
    cpOpenDialog(mode, options = {}) {
        this.dialogService.add(DependencyDialog, { model: this.model, records: this.model.data.records, mode, ...options });
    },
    shouldRenderConnectors() {
        return super.shouldRenderConnectors(...arguments) && this.cpDependencyUI?.visible !== false;
    },
    enrichPill(pill) {
        const result = super.enrichPill(...arguments);
        if (enhanced(this.model) && result?.record.is_critical) {
            result.className = `${result.className || ""} o_cp_critical_task`;
        }
        return result;
    },
    getConnecterValues(source, target) {
        const values = super.getConnecterValues(...arguments);
        if (enhanced(this.model)) {
            const { dateStartField, dateStopField } = this.model.metaData;
            const visual = visualDependency(source.record, target.record,
                target.record.gantt_dependency_metadata?.[source.record.id], dateStartField, dateStopField);
            values[0].cpData = { ...visual, rtl: localization.direction === "rtl",
                title: `${source.record.display_name} → ${typeNames[visual.type]}${visual.lag ? ` ${visual.lag > 0 ? "+" : ""}${visual.lag} d` : ""} → ${target.record.display_name}`,
                edit: () => this.cpOpenDialog("edit", { sourceId: source.record.id, targetId: target.record.id }),
                canEdit: this.model.metaData.canEdit,
            };
            values[0].alert = visual.invalid ? "error" : null;
        }
        return values;
    },
    setConnector(params, sourceId = null, targetId = null, dashed = null) {
        if (!params.cpData) {
            return super.setConnector(...arguments);
        }
        const id = params.id || `__connector__${this.nextConnectorId++}`;
        super.setConnector({ ...params, id }, sourceId, targetId, dashed);
        this.connectors[id].sourcePoint = () => this.getPoint(sourceId, params.cpData.type[0] === "F");
        this.connectors[id].targetPoint = () => this.getPoint(targetId, params.cpData.type[1] === "F");
    },
});

patch(GanttRendererControls.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.model.cpDependencyUI) {
            this.cpDependencyUI = useState(this.model.cpDependencyUI);
        }
    },
});

patch(GanttConnector, {
    props: { ...GanttConnector.props, reactive: { ...GanttConnector.props.reactive,
        shape: { ...GanttConnector.props.reactive.shape, cpData: { type: Object, optional: true } },
    } },
});

patch(GanttConnector.prototype, {
    setup() {
        super.setup(...arguments);
        onWillRender(() => {
            const data = this.props.reactive.cpData;
            if (data) {
                this.style.stroke.color = this.highlighted ? "var(--o-cp-dependency-selected, #71639e)" :
                    data.invalid ? "var(--o-cp-dependency-invalid, #dc3545)" :
                    data.critical ? "var(--o-cp-dependency-critical, #c93756)" : "var(--o-cp-dependency-normal, #8f8f8f)";
            }
        });
        useEffect((element, sourceLeft, sourceTop, targetLeft, targetTop) => {
            const data = this.props.reactive.cpData;
            if (!data || !element) {
                return;
            }
            const geometry = dependencyGeometry({ left: sourceLeft, top: sourceTop }, { left: targetLeft, top: targetTop }, data.type, data.rtl);
            for (const path of element.querySelectorAll(".o_connector_stroke, .o_connector_stroke_hover_ease, .o_connector_stroke_outline")) {
                path.setAttribute("d", geometry.path);
            }
            const label = element.querySelector(".o_cp_dependency_label");
            label?.setAttribute("x", geometry.label.x);
            label?.setAttribute("y", geometry.label.y);
            const buttons = element.querySelector(".o_connector_stroke_buttons");
            buttons?.setAttribute("x", geometry.label.x - 30);
            buttons?.setAttribute("y", geometry.label.y + 10);
        }, () => [...this.getEffectDependencies(), this.props.reactive.cpData]);
    },
    cpEdit(event) {
        const data = this.props.reactive.cpData;
        if (data && !event.target.closest(".o_connector_stroke_buttons")) {
            event.stopPropagation();
            data.edit();
        }
    },
});
