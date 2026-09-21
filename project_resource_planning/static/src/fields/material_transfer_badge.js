/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Material Plan → Transfer badge (BRD): a single list cell rendering the
// truck icon with a corner count badge. 0 → empty cell, 1 → picking form,
// >1 → filtered standard stock.picking list. Navigation delegates to the
// existing action_open_transfers server method — no custom screens.
export class MaterialTransferBadge extends Component {
    static template = "project_critical_path.MaterialTransferBadge";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get count() {
        return this.props.record.data.picking_count || 0;
    }

    async openTransfers(ev) {
        ev.stopPropagation();
        if (!this.count || !this.props.record.resId) {
            return;
        }
        const action = await this.orm.call(
            "project.material.plan", "action_open_transfers",
            [[this.props.record.resId]],
        );
        if (action) {
            await this.action.doAction(action);
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            this.openTransfers(ev);
        }
    }
}

registry.category("fields").add("material_transfer_badge", {
    component: MaterialTransferBadge,
    supportedTypes: ["integer"],
});
