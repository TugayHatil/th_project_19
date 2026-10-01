# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Backfill allocated_hours for dated leaf tasks that predate the
    write-hook resync.

    Before 19.0.9.0.0 tasks scheduled outside the planner (form edits,
    RPC, imports) kept allocated_hours at 0, so the CPM treated them as
    zero-duration nodes and every path tied as "critical". The seed is
    write-time only, so existing rows are fixed here once. Parents are
    skipped — they roll a window up from children but carry no work.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    tasks = env["project.task"].with_context(
        active_test=False, cp_skip_recalc=True, cp_skip_auto_schedule=True,
    ).search([
        ("date_assign", "!=", False),
        ("date_deadline", "!=", False),
        ("allocated_hours", "<=", 0.0),
        ("child_ids", "=", False),
    ])
    tasks._resync_allocated_hours()
    # One recalc per affected project instead of per task.
    tasks.mapped("project_id")._recalculate_critical_paths()
