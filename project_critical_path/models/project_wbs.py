# -*- coding: utf-8 -*-

from collections import defaultdict
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ProjectTaskWBS(models.Model):
    _inherit = "project.task"
    _order = "wbs_sort_key asc, sequence asc, id asc"


    wbs_code = fields.Char(
        string="WBS Code",
        compute="_compute_wbs_code_and_level",
        store=True,
        readonly=True,
        index=True,
        copy=False,
    )
    wbs_level = fields.Integer(
        string="WBS Level",
        compute="_compute_wbs_code_and_level",
        store=True,
        readonly=True,
        index=True,
        copy=False,
        default=1,
    )
    wbs_sort_key = fields.Char(
        string="WBS Sort Key",
        compute="_compute_wbs_code_and_level",
        store=True,
        readonly=True,
        index=True,
        copy=False,
    )
    is_work_package = fields.Boolean(
        string="Work Package",
        compute="_compute_is_work_package",
        store=True,
        readonly=True,
        index=True,
        copy=False,
        default=False,
    )
    planned_hours_rollup = fields.Float(
        string="Planned Hours Roll-up",
        compute="_compute_wbs_rollups",
        store=True,
        readonly=True,
        copy=False,
        digits=(16, 2),
    )
    effective_hours_rollup = fields.Float(
        string="Actual Hours Roll-up",
        compute="_compute_wbs_rollups",
        store=True,
        readonly=True,
        copy=False,
        digits=(16, 2),
    )
    progress_rollup = fields.Float(
        string="Progress Roll-up (%)",
        compute="_compute_wbs_rollups",
        store=True,
        readonly=True,
        copy=False,
        digits=(16, 2),
    )

    @api.depends("parent_id", "sequence", "project_id", "child_ids")
    def _compute_wbs_code_and_level(self):
        projects = self.mapped("project_id")
        for project in projects:
            project_tasks = self.env["project.task"].with_context(active_test=False).search(
                [("project_id", "=", project.id)]
            )
            codes, levels, sort_keys = project._calculate_wbs_codes_map(project_tasks)
            for task in project_tasks:
                if task in self:
                    task.wbs_code = codes.get(task.id, "")
                    task.wbs_level = levels.get(task.id, 1)
                    task.wbs_sort_key = sort_keys.get(task.id, "")

        for task in self:
            if not task.project_id:
                task.wbs_code = ""
                task.wbs_level = 1
                task.wbs_sort_key = ""

    @api.depends("child_ids")
    def _compute_is_work_package(self):
        for task in self:
            task.is_work_package = bool(task.child_ids)

    @api.depends(
        "allocated_hours",
        "progress",
        "child_ids",
        "child_ids.planned_hours_rollup",
        "child_ids.progress_rollup",
    )
    def _compute_wbs_rollups(self):
        projects = self.mapped("project_id")
        for project in projects:
            project_tasks = self.env["project.task"].with_context(active_test=False).search(
                [("project_id", "=", project.id)]
            )
            rollups = project._calculate_wbs_rollups_map(project_tasks)
            for task in project_tasks:
                if task in self:
                    p, e, prog = rollups.get(task.id, (0.0, 0.0, 0.0))
                    task.planned_hours_rollup = p
                    task.effective_hours_rollup = e
                    task.progress_rollup = prog

        for task in self:
            if not task.project_id:
                p = task.allocated_hours or 0.0
                e = getattr(task, "effective_hours", 0.0) or 0.0
                prog = task.progress or 0.0
                task.planned_hours_rollup = p
                task.effective_hours_rollup = e
                task.progress_rollup = round(prog, 2)

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        projects = tasks.mapped("project_id")
        if projects:
            projects._recalculate_wbs()
        return tasks

    def write(self, vals):
        if "parent_id" in vals:
            if not self.env.user.has_group("project.group_project_manager"):
                for task in self:
                    if task.parent_id.id != vals["parent_id"]:
                        raise UserError(_("Only Project Managers are allowed to modify the WBS task hierarchy."))

        affected_projects = self.mapped("project_id")
        result = super().write(vals)
        all_projects = affected_projects | self.mapped("project_id")

        wbs_trigger_fields = {
            "parent_id",
            "sequence",
            "project_id",
            "allocated_hours",
            "progress",
        }
        if wbs_trigger_fields.intersection(vals):
            all_projects._recalculate_wbs()

        return result

    def unlink(self):
        affected_projects = self.mapped("project_id")
        result = super().unlink()
        if affected_projects:
            affected_projects._recalculate_wbs()
        return result





class ProjectProjectWBS(models.Model):
    _inherit = "project.project"

    def _calculate_wbs_codes_map(self, tasks=None):
        self.ensure_one()
        if tasks is None:
            tasks = self.env["project.task"].with_context(active_test=False).search(
                [("project_id", "=", self.id)]
            )

        children_by_parent = defaultdict(list)
        for task in tasks:
            children_by_parent[task.parent_id.id].append(task)

        for parent_id in children_by_parent:
            children_by_parent[parent_id].sort(key=lambda t: (t.sequence, t.id))

        codes = {}
        levels = {}
        sort_keys = {}

        def assign_wbs(parent_task, parent_wbs, level):
            parent_key = parent_task.id if parent_task else False
            children = children_by_parent.get(parent_key, [])
            for idx, child in enumerate(children, start=1):
                code = f"{parent_wbs}.{idx}" if parent_wbs else str(idx)
                sort_key = ".".join(f"{int(part):04d}" for part in code.split("."))
                codes[child.id] = code
                levels[child.id] = level
                sort_keys[child.id] = sort_key
                assign_wbs(child, code, level + 1)

        assign_wbs(None, "", 1)
        return codes, levels, sort_keys

    def _calculate_wbs_rollups_map(self, tasks=None):
        self.ensure_one()
        if tasks is None:
            tasks = self.env["project.task"].with_context(active_test=False).search(
                [("project_id", "=", self.id)]
            )

        task_by_id = {t.id: t for t in tasks}
        children_by_parent = defaultdict(list)
        for t in tasks:
            children_by_parent[t.parent_id.id].append(t.id)

        cache = {}

        def compute_node(t_id):
            if t_id in cache:
                return cache[t_id]

            t = task_by_id[t_id]
            p = t.allocated_hours or 0.0
            e = getattr(t, "effective_hours", 0.0) or 0.0
            prog = t.progress or 0.0
            wp = prog * p
            sum_prog = prog
            cnt = 1

            for child_id in children_by_parent.get(t_id, []):
                cp, ce, cwp, csum_prog, ccnt = compute_node(child_id)
                p += cp
                e += ce
                wp += cwp
                sum_prog += csum_prog
                cnt += ccnt

            cache[t_id] = (p, e, wp, sum_prog, cnt)
            return cache[t_id]

        for t_id in task_by_id:
            compute_node(t_id)

        rollups = {}
        for t_id, (p, e, wp, sum_prog, cnt) in cache.items():
            if p > 0:
                prog_rollup = wp / p
            else:
                prog_rollup = (sum_prog / cnt) if cnt > 0 else 0.0

            rollups[t_id] = (round(p, 2), round(e, 2), round(prog_rollup, 2))

        return rollups

    def _recalculate_wbs(self):
        for project in self:
            tasks = self.env["project.task"].with_context(active_test=False).search(
                [("project_id", "=", project.id)]
            )
            if not tasks:
                continue
            codes, levels, sort_keys = project._calculate_wbs_codes_map(tasks)
            rollups = project._calculate_wbs_rollups_map(tasks)

            for task in tasks:
                has_children = bool(task.child_ids)
                p, e, prog = rollups.get(task.id, (0.0, 0.0, 0.0))
                code = codes.get(task.id, "")
                lvl = levels.get(task.id, 1)
                sort_key = sort_keys.get(task.id, "")

                vals = {}
                if task.wbs_code != code:
                    vals["wbs_code"] = code
                if task.wbs_level != lvl:
                    vals["wbs_level"] = lvl
                if task.wbs_sort_key != sort_key:
                    vals["wbs_sort_key"] = sort_key
                if task.is_work_package != has_children:
                    vals["is_work_package"] = has_children
                if task.planned_hours_rollup != p:
                    vals["planned_hours_rollup"] = p
                if task.effective_hours_rollup != e:
                    vals["effective_hours_rollup"] = e
                if task.progress_rollup != prog:
                    vals["progress_rollup"] = prog

                if vals:
                    task.write(vals)

    def _recalculate_wbs_codes(self):
        self._recalculate_wbs()

    def _recalculate_wbs_rollups(self):
        self._recalculate_wbs()
