/** @odoo-module */

import { BooleanField, booleanField } from "@web/views/fields/boolean/boolean_field";
import { registry } from "@web/core/registry";
import { xml } from "@odoo/owl";

export class AlternativeRadioField extends BooleanField {
    /**
     * The checkbox stays enabled in the list's readonly rendering so a
     * single click toggles the selection instead of merely activating
     * the row's edit mode. In non-partial mode, checking an option also
     * clears the other options of the same component (move) so only one
     * option can ever be selected.
     */
    async onChange(ev) {
        const newValue = ev.target.checked;
        const record = this.props.record;
        const parent = record.model.root;
        if (parent.data.allow_partial) {
            await record.update({ [this.props.name]: newValue });
            return;
        }
        // Non-partial mode: the applied quantity is always the full
        // demand of the chosen option (in that product's uom).
        await record.update({
            [this.props.name]: newValue,
            selected_qty: newValue ? record.data.demand_qty : 0,
        });
        if (!newValue) {
            return;
        }
        const moveId = this._moveId(record.data.move_id);
        for (const line of parent.data.line_ids.records) {
            if (line === this.props.record || !line.data.selected) {
                continue;
            }
            if (this._moveId(line.data.move_id) === moveId) {
                line.update({ selected: false });
            }
        }
    }

    _moveId(value) {
        if (!value) {
            return false;
        }
        return Array.isArray(value) ? value[0] : value.id;
    }
}

AlternativeRadioField.template = xml`
    <input type="checkbox" class="o_checkbox form-check-input"
           t-att-checked="props.record.data[props.name]"
           t-on-change="onChange"/>
`;

export const alternativeRadioField = {
    ...booleanField,
    component: AlternativeRadioField,
};

registry.category("fields").add("alternative_radio", alternativeRadioField);
