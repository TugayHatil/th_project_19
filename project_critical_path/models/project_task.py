# -*- coding: utf-8 -*-

from odoo import api, fields, models

from .project_planner import _task_window_hours, check_planner_manager

# Planner-managed data (BRD Planner Manager): only members of
# group_planner_manager may touch these — whether via the Planner, the
# task form or RPC. Everything the Planner exposes as editable is here:
# name, schedule, duration, assignee, dependencies, hierarchy
# and WBS order. The check runs on the incoming vals only, so internal
# writes (the ``date_done`` stamp on state changes, parent rollups, WBS
# recomputes under a member's request) still work for every user.
# Workflow fields (stage_id, state, description, tags) stay free —
# closing a task is a task operation, not a planner edit.
# WBS code/level/sort_key/work_package, ``progress`` and ``date_done``
# are deliberately NOT here: they are computed/rollup-driven fields whose
# assignments re-enter write() during recomputes (e.g. the date_done
# stamp/clear on every state transition) and would break normal task
# updates for non-members. ``date_done`` is readonly anyway; ``progress``
# stays reachable through the gated update_planner_task.
PLANNER_GUARDED_FIELDS = frozenset({
    "name", "user_ids", "allocated_hours", "sequence",
    "date_assign", "date_deadline",
    "depend_on_ids", "dependent_ids",
    "parent_id",
})
# Creating a task always carries ``name`` — on create only the planner
# attributes are gated so a bare task can still be created by anyone
# with Odoo's own create rights.
PLANNER_GUARDED_CREATE_FIELDS = PLANNER_GUARDED_FIELDS - {"name"}


class ProjectTask(models.Model):
    _inherit = "project.task"

    critical_early_start = fields.Float(string="Early Start", readonly=True)
    critical_early_finish = fields.Float(string="Early Finish", readonly=True)
    critical_late_start = fields.Float(string="Late Start", readonly=True)
    critical_late_finish = fields.Float(string="Late Finish", readonly=True)
    critical_slack = fields.Float(string="Slack", readonly=True)
    is_critical = fields.Boolean(string="Critical Task", readonly=True)
    delay_baseline_duration = fields.Float(string="Baseline Duration", readonly=True)
    delay_duration_variance = fields.Float(string="Duration Variance", readonly=True)
    delay_project_impact = fields.Float(string="Project Impact", readonly=True)
    delay_impact_status = fields.Selection([
        ("critical_impact", "Critical Impact"),
        ("within_slack", "Within Slack"),
        ("duration_reduced", "Duration Reduced"),
        ("no_impact", "No Impact"),
    ], string="Impact Status", readonly=True)
    delay_impact_chain = fields.Text(string="Impact Chain", readonly=True)

    # Finish Variance (BRD): the actual close timestamp, stamped when the
    # task moves to the done state and cleared on reopen. Computed+stored
    # (not write-injected) so EVERY reopen path — stage change, is_closed
    # inverse, direct state write, RPC — clears it; state is a stored
    # computed field and its flush-time updates never re-enter write().
    # An existing explicit value is preserved while the task stays done.
    date_done = fields.Datetime(
        string="Actual Finish", readonly=True, copy=False,
        compute="_compute_date_done", store=True,
    )
    # Stored so the Planner status filters (Completed Late/Early/On Time)
    # can search it directly as a project.task domain leaf.
    finish_variance_state = fields.Selection(
        [
            ("late", "Completed Late"),
            ("early", "Completed Early"),
            ("on_time", "Completed On Time"),
        ],
        string="Finish Variance",
        compute="_compute_finish_variance_state",
        store=True,
        readonly=True,
    )

    @api.depends("state")
    def _compute_date_done(self):
        now = fields.Datetime.now()
        for task in self:
            if task.state == "1_done":
                if not task.date_done:
                    task.date_done = now
            else:
                task.date_done = False

    @api.depends("state", "date_done", "date_deadline")
    def _compute_finish_variance_state(self):
        # BRD v2: whole-day variance only — closing later in the SAME day
        # is still on time; the hour component never counts.
        for task in self:
            if task.state != "1_done" or not task.date_done or not task.date_deadline:
                task.finish_variance_state = False
                continue
            # Compare calendar days in the user's timezone — the same
            # frame the planner payload serializes dates in.
            done_day = fields.Datetime.context_timestamp(task, task.date_done).date()
            stop_day = fields.Datetime.context_timestamp(task, task.date_deadline).date()
            if done_day > stop_day:
                task.finish_variance_state = "late"
            elif done_day < stop_day:
                task.finish_variance_state = "early"
            else:
                task.finish_variance_state = "on_time"

    def _planner_effective_done(self):
        """Actual close used by the Finish Variance tail.

        The tail is tied to the task's OWN done state: ``date_done`` is a
        computed stamp that exists only while ``state == "1_done"``, so an
        open task — including a parent whose children are all closed —
        reports no effective close.
        """
        self.ensure_one()
        return self.date_done

    def _planner_resource_fields(self):
        """Resource labels/summary for the planner payload.

        Empty hook in the core addon — ``project_resource_planning``
        overrides it with the task's real role names/categories and the
        human/equipment/open counts used by the row badges.
        """
        return {
            "role_names": [],
            "role_categories": [],
        }

    @api.model_create_multi
    def create(self, vals_list):
        if any(
            PLANNER_GUARDED_CREATE_FIELDS.intersection(vals)
            for vals in vals_list
        ):
            check_planner_manager(self.env)
        # Odoo stamps ``date_assign`` with "now" when assignees are present
        # at create time — and does so after create() returns (flush-time
        # subscription machinery), so it cannot be repaired afterwards.
        # The stamp is meant as "assigned today"; a caller who supplies an
        # explicit planned start wants that kept, so the assignee set is
        # deferred to a follow-up write — plain writes never re-stamp.
        deferred_assignees = [
            vals.pop("user_ids") if vals.get("user_ids") and vals.get("date_assign") else None
            for vals in vals_list
        ]
        tasks = super().create(vals_list)
        for task, user_ids_command in zip(tasks, deferred_assignees):
            if user_ids_command is not None:
                task.with_context(
                    cp_skip_recalc=True, cp_skip_auto_schedule=True,
                ).write({"user_ids": user_ids_command})
        # Tasks created with a full window but no explicit duration derive
        # theirs from the span — same convention as planner drags.
        to_seed = self.env["project.task"]
        for task, vals in zip(tasks, vals_list):
            if "allocated_hours" not in vals:
                to_seed += task
        to_seed._resync_allocated_hours()
        # Bulk imports can pass cp_skip_recalc and then call
        # action_calculate_critical_paths once — otherwise every batch
        # would rerun the full project CPM.
        if not self.env.context.get("cp_skip_recalc"):
            tasks.mapped("project_id")._recalculate_critical_paths()
        tasks.mapped("parent_id")._sync_parent_window()
        return tasks

    def write(self, vals):
        if PLANNER_GUARDED_FIELDS.intersection(vals):
            check_planner_manager(self.env)
        affected_projects = self.mapped("project_id")
        old_parents = self.mapped("parent_id") if "parent_id" in vals else self.env["project.task"]
        result = super().write(vals)
        # "The window defines the duration" — the planner derives
        # allocated_hours from the date span on every drag, but writes
        # that bypass it (form edits, RPC, imports, cascading shifts)
        # leave the field at 0/stale while CPM uses it as the duration
        # source. Resync before the recalc below so one pass sees the
        # fresh durations. An explicit allocated_hours in the same write
        # stays authoritative; parents roll a window up from children but
        # carry no work, so they are skipped inside.
        if {"date_assign", "date_deadline"}.intersection(vals) and "allocated_hours" not in vals:
            self._resync_allocated_hours()
        # allocated_hours is a stored compute over the date window, so a
        # date change alters durations without naming the field — include
        # the dates in the trigger set or CPM goes stale after drags.
        if {"project_id", "parent_id", "allocated_hours", "planned_date_begin", "depend_on_ids", "dependent_ids", "date_assign", "date_deadline"}.intersection(vals) and not self.env.context.get(
            "cp_skip_recalc"
        ) and not self.env.context.get("cp_skip_auto_schedule"):
            (affected_projects | self.mapped("project_id"))._recalculate_critical_paths()
        # BRD auto-shift: a date change can violate successor dependency
        # bounds — the cascade runs once per project and suppresses its
        # own re-trigger via context.
        if {"date_assign", "date_deadline"}.intersection(vals) and not self.env.context.get(
            "cp_skip_auto_schedule"
        ):
            for project in self.mapped("project_id"):
                project._schedule_dependents(
                    self.filtered(lambda task: task.project_id == project)
                )
        # Parent window rollup: a parent's date range mirrors the min/max of
        # its dated children. The parent write re-enters this hook, so the
        # rollup bubbles all the way to the root.
        if {"date_assign", "date_deadline", "parent_id"}.intersection(vals):
            (self.mapped("parent_id") | old_parents)._sync_parent_window()
        return result

    def _resync_allocated_hours(self):
        """Write the window-derived duration into ``allocated_hours``.

        Leaf tasks only — WBS parents get their window rolled up from
        children but do no work of their own, so they must stay at 0 or
        the CPM graph would double-count the same span. Seed-once only:
        a non-zero allocated_hours is authoritative (inspector edits and
        explicit RPC writes must survive later window changes), so this
        never overwrites it. Writes carry the skip flags — the triggering
        write already schedules the recalc.
        """
        for task in self:
            if (
                task.child_ids
                or task.allocated_hours
                or not (task.date_assign and task.date_deadline)
            ):
                continue
            hours = _task_window_hours(task)
            if hours > 0.000001:
                task.with_context(
                    cp_skip_recalc=True, cp_skip_auto_schedule=True,
                ).write({"allocated_hours": hours})

    def _sync_parent_window(self):
        """``self`` = parent tasks — recompute each one's date window as the
        min/max over its dated children, so parent bars stay consistent with
        the WBS children after moves, resizes and cascade shifts."""
        for parent in self:
            children = parent.child_ids.filtered(
                lambda child: child.date_assign and child.date_deadline
            )
            if not children:
                continue
            start = min(children.mapped("date_assign"))
            stop = max(children.mapped("date_deadline"))
            vals = {}
            if parent.date_assign != start:
                vals["date_assign"] = start
            if parent.date_deadline != stop:
                vals["date_deadline"] = stop
            if vals:
                # The parent window is a rollup — it must not re-enter the
                # auto-shift cascade or fire another full CPM per level;
                # the triggering write already scheduled one recalc.
                parent.with_context(
                    cp_skip_auto_schedule=True, cp_skip_recalc=True,
                ).write(vals)

    def unlink(self):
        # Deleting a planned task deletes planner data — only Planner
        # Managers may remove tasks that carry a schedule, dependencies or
        # a place in the WBS hierarchy. Bare tasks stay deletable.
        if not self.env.su and not self.env.user.has_group(
            "project_critical_path.group_planner_manager"
        ) and self.filtered(
            lambda task: task.date_assign or task.date_deadline
            or task.depend_on_ids or task.dependent_ids
            or task.child_ids or task.parent_id
        ):
            check_planner_manager(self.env)
        affected_projects = self.mapped("project_id")
        result = super().unlink()
        affected_projects._recalculate_critical_paths()
        return result
