/** @odoo.module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { FileInput } from "@web/core/file_input/file_input";
import { useX2ManyCrud } from "@web/views/fields/relational_utils";

import { Component } from "@odoo/owl";

export class MpnAttachmentsField extends Component {
    static template = "product_multi_manufacturer.MpnAttachments";
    static components = { FileInput };
    static props = { ...standardFieldProps };

    setup() {
        this.notification = useService("notification");
        this.operations = useX2ManyCrud(
            () => this.props.record.data[this.props.name],
            true
        );
    }

    get files() {
        return this.props.record.data[this.props.name].records.map((record) => ({
            ...record.data,
            id: record.resId,
        }));
    }

    isPdf(file) {
        return file.mimetype === "application/pdf";
    }

    // PDF yeni sekmede onizlenir, diger dosyalar indirilir.
    urlFor(file) {
        return this.isPdf(file)
            ? `/web/content/${file.id}`
            : `/web/content/${file.id}?download=true`;
    }

    iconFor(file) {
        const mimetype = file.mimetype || "";
        if (mimetype === "application/pdf") {
            return "fa-file-pdf-o";
        }
        if (mimetype.startsWith("image/")) {
            return "fa-file-image-o";
        }
        if (mimetype.includes("word")) {
            return "fa-file-word-o";
        }
        if (mimetype.includes("excel") || mimetype.includes("spreadsheet") || mimetype === "text/csv") {
            return "fa-file-excel-o";
        }
        if (mimetype.startsWith("text/")) {
            return "fa-file-text-o";
        }
        return "fa-file-o";
    }

    async onFileUploaded(files) {
        for (const file of files) {
            if (file.error) {
                return this.notification.add(file.error, {
                    title: _t("Uploading error"),
                    type: "danger",
                });
            }
            await this.operations.saveRecord([file.id]);
        }
    }

    onFileRemove(deleteId) {
        const record = this.props.record.data[this.props.name].records.find(
            (r) => r.resId === deleteId
        );
        this.operations.removeRecord(record);
    }
}

export const mpnAttachmentsField = {
    component: MpnAttachmentsField,
    supportedTypes: ["many2many"],
    isEmpty: () => false,
    relatedFields: [
        { name: "name", type: "char" },
        { name: "mimetype", type: "char" },
    ],
};

registry.category("fields").add("mpn_attachments", mpnAttachmentsField);
