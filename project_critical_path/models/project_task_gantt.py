from math import isfinite

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectTaskGantt(models.Model):
    _inherit = "project.task"

    gantt_dependency_metadata = fields.Json(
        string="Dependency Visualization", default=dict, copy=False, readonly=True,
        groups="base.group_user",
        help="Visual type and lag keyed by native predecessor ID. Does not change scheduling or CPM.",
    )

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == "gantt" and arch.tag == "gantt":
            dependency_field = arch.get("dependency_field")
            if not dependency_field or dependency_field == "depend_on_ids":
                arch.set("dependency_field", "depend_on_ids")
                arch.set("dependency_inverted_field", "dependent_ids")
                for name in ("depend_on_ids", "dependent_ids", "is_critical", "gantt_dependency_metadata"):
                    if not arch.xpath("field[@name=$name]", name=name):
                        etree.SubElement(arch, "field", name=name)
        return arch, view

    @api.model
    def _validate_gantt_dependency_values(self, kind, lag):
        if kind not in ("FS", "SS", "FF", "SF"):
            raise ValidationError(_("Choose FS, SS, FF or SF as the dependency type."))
        if isinstance(lag, bool) or not isinstance(lag, (float, int)) or not isfinite(lag):
            raise ValidationError(_("Lag must be a finite number of days."))

    @api.constrains("gantt_dependency_metadata")
    def _check_gantt_dependency_metadata(self):
        for task in self:
            metadata = task.gantt_dependency_metadata
            if metadata is False or metadata is None:
                continue
            if not isinstance(metadata, dict):
                raise ValidationError(_("Invalid dependency visualization data."))
            native_ids = {str(task_id) for task_id in task.depend_on_ids.ids}
            for predecessor_id, values in metadata.items():
                if predecessor_id not in native_ids or not isinstance(values, dict) or set(values) != {"type", "lag"}:
                    raise ValidationError(_("Visualization data must refer to an existing native dependency."))
                self._validate_gantt_dependency_values(values["type"], values["lag"])

    def _lock_gantt_dependency(self):
        self.ensure_one()
        self.check_access("write")
        self.env.cr.execute("SELECT id FROM project_task WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset(["depend_on_ids", "gantt_dependency_metadata"])

    def set_gantt_dependency(self, predecessor_id, dependency_type="FS", lag=0.0, create=False):
        self._lock_gantt_dependency()
        self._validate_gantt_dependency_values(dependency_type, lag)
        if type(predecessor_id) is not int or predecessor_id <= 0:
            raise ValidationError(_("Choose a predecessor task."))
        predecessor = self.browse(predecessor_id).exists()
        if not predecessor:
            raise ValidationError(_("The predecessor task no longer exists."))
        predecessor.check_access("read")
        if predecessor == self:
            raise ValidationError(_("A task cannot depend on itself."))
        linked = predecessor in self.depend_on_ids
        if create and linked:
            raise ValidationError(_("These tasks are already linked. Edit the existing dependency instead."))
        if not create and not linked:
            raise ValidationError(_("This dependency no longer exists. Refresh the Gantt view."))
        metadata = dict(self.gantt_dependency_metadata or {})
        metadata[str(predecessor_id)] = {"type": dependency_type, "lag": float(lag)}
        values = {"gantt_dependency_metadata": metadata}
        if create:
            values["depend_on_ids"] = [fields.Command.link(predecessor_id)]
        self.write(values)
        return True

    def remove_gantt_dependency(self, predecessor_id):
        self._lock_gantt_dependency()
        if type(predecessor_id) is not int or predecessor_id <= 0:
            raise ValidationError(_("Choose a predecessor task."))
        metadata = dict(self.gantt_dependency_metadata or {})
        metadata.pop(str(predecessor_id), None)
        self.write({
            "depend_on_ids": [fields.Command.unlink(predecessor_id)],
            "gantt_dependency_metadata": metadata,
        })
        return True

    def write(self, vals):
        affected = self.browse()
        if "depend_on_ids" in vals:
            affected |= self
        if "dependent_ids" in vals:
            affected |= self.dependent_ids
        result = super().write(vals)
        if "dependent_ids" in vals:
            affected |= self.dependent_ids
        if affected:
            if affected._has_cycle("depend_on_ids"):
                raise ValidationError(_("Circular dependencies are not allowed."))
            for task in affected:
                metadata = task.gantt_dependency_metadata or {}
                native_ids = {str(task_id) for task_id in task.depend_on_ids.ids}
                cleaned = {key: value for key, value in metadata.items() if key in native_ids}
                if cleaned != metadata:
                    task.write({"gantt_dependency_metadata": cleaned})
        return result
