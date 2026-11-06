/** @odoo-module */

import { BooleanField, booleanField } from "@web/views/fields/boolean/boolean_field";
import { registry } from "@web/core/registry";

export class AlternativeRadioField extends BooleanField {
    /**
     * Radio behaviour for the alternative selector: in non-partial mode,
     * checking an option clears the other options of the same component
     * (move) so only one option can ever be selected.
     */
    async onChange(newValue) {
        await super.onChange(newValue);
        if (!newValue) {
            return;
        }
        const record = this.props.record;
        const parent = record.model.root;
        if (parent.data.allow_partial) {
            return;
        }
        const moveId = this._moveId(record.data.move_id);
        for (const line of parent.data.line_ids.records) {
            if (line === record || !line.data.selected) {
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

export const alternativeRadioField = {
    ...booleanField,
    component: AlternativeRadioField,
};

registry.category("fields").add("alternative_radio", alternativeRadioField);
