/** @odoo.module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useX2ManyCrud } from "@web/views/fields/relational_utils";
import { Dialog } from "@web/core/dialog/dialog";

import { Component, useState } from "@odoo/owl";

export class MpnSelectDialog extends Component {
    static template = "product_multi_manufacturer.MpnSelectDialog";
    static components = { Dialog };
    static props = {
        title: { type: String },
        options: { type: Array },   // [{id, code, manufacturer}]
        selected: { type: Array },  // secili id'ler
        confirm: { type: Function },
        close: { type: Function },
    };

    setup() {
        this.state = useState({ selected: new Set(this.props.selected) });
    }

    get allSelected() {
        return this.props.options.length > 0
            && this.state.selected.size === this.props.options.length;
    }

    toggleAll() {
        this.state.selected = this.allSelected
            ? new Set()
            : new Set(this.props.options.map((o) => o.id));
    }

    toggle(id) {
        if (this.state.selected.has(id)) {
            this.state.selected.delete(id);
        } else {
            this.state.selected.add(id);
        }
    }

    async onConfirm() {
        await this.props.confirm([...this.state.selected]);
        this.props.close();
    }
}

export class MpnTagsField extends Component {
    static template = "product_multi_manufacturer.MpnTags";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.operations = useX2ManyCrud(
            () => this.props.record.data[this.props.name],
            true
        );
    }

    get tags() {
        return this.props.record.data[this.props.name].records.map((record) => ({
            ...record.data,
            id: record.resId,
        }));
    }

    get productId() {
        const value = this.props.record.data.product_id;
        if (!value) {
            return false;
        }
        if (Array.isArray(value)) {
            return value[0];
        }
        if (typeof value === "object") {
            return value.id || value.resId || false;
        }
        return value;
    }

    async openDialog() {
        const productId = this.productId;
        if (!productId) {
            this.notification.add(_t("Önce satırda bir ürün seçin."), {
                type: "warning",
            });
            return;
        }
        const mpns = await this.orm.searchRead(
            "product.manufacturer",
            [["product_id", "=", productId]],
            ["manufacturer_code", "manufacturer_id"]
        );
        this.dialog.add(MpnSelectDialog, {
            title: _t("MPN Seç"),
            options: mpns.map((m) => ({
                id: m.id,
                code: m.manufacturer_code,
                manufacturer: m.manufacturer_id ? m.manufacturer_id[1] : "",
            })),
            selected: this.tags.map((t) => t.id),
            confirm: async (ids) => {
                await this.props.record.update({
                    [this.props.name]: [[6, 0, ids]],
                });
            },
        });
    }

    onRemove(deleteId) {
        const record = this.props.record.data[this.props.name].records.find(
            (r) => r.resId === deleteId
        );
        this.operations.removeRecord(record);
    }
}

export const mpnTagsField = {
    component: MpnTagsField,
    supportedTypes: ["many2many"],
    isEmpty: () => false,
    relatedFields: [
        { name: "manufacturer_code", type: "char" },
        { name: "manufacturer_id", type: "many2one", relation: "res.partner" },
    ],
};

registry.category("fields").add("mpn_tags", mpnTagsField);
