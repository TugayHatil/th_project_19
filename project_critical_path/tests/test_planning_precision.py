# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestPlanningPrecision(TransactionCase):
    """BRD Planning Precision — a per-project hour/day planning granularity.

    The parameter is display/input precision only: the datetime storage,
    the dependency engine, CPM, baselines and rollups keep working exactly
    as before. Switching precision must never mutate task data.
    """

    def _make_task(self, project, name, **values):
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
            **values,
        })

    def test_default_precision_is_hour(self):
        """Test A — new projects default to hour precision so existing
        behaviour never changes."""
        project = self.env["project.project"].create({"name": "Default"})
        self.assertEqual(project.planning_precision, "hour")

    def test_precision_persists_day(self):
        """Test B — the selection is stored per project."""
        project = self.env["project.project"].create(
            {"name": "Day", "planning_precision": "day"}
        )
        self.assertEqual(project.planning_precision, "day")
        project.planning_precision = "hour"
        self.assertEqual(project.planning_precision, "hour")

    def test_payload_exposes_precision(self):
        """The planner payload carries the precision + hours_per_day so the
        frontend can render day-based durations/lag/slack."""
        day = self.env["project.project"].create(
            {"name": "Day payload", "planning_precision": "day"}
        )
        hour = self.env["project.project"].create({"name": "Hour payload"})
        self.assertEqual(day.get_planner_data()["project"]["planning_precision"], "day")
        self.assertEqual(hour.get_planner_data()["project"]["planning_precision"], "hour")
        self.assertGreater(
            day.get_planner_data()["project"]["hours_per_day"], 0.0
        )

    def test_day_duration_inclusive(self):
        """Test C/D — inclusive calendar-day span: 16→18 = 3 days,
        16→16 = 1 day. The day-span convention already lives in
        update_planner_task via duration_days."""
        project = self.env["project.project"].create(
            {"name": "Duration", "planning_precision": "day"}
        )
        task = self._make_task(project, "Task")
        task.update_planner_task({
            "date_start": "2026-10-16",
            "date_stop": "2026-10-18",
            "duration_days": 3,
        })
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["date_start"], "2026-10-16")
        self.assertEqual(row["date_stop"], "2026-10-18")

        task.update_planner_task({
            "date_start": "2026-10-16",
            "date_stop": "2026-10-16",
            "duration_days": 1,
        })
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["date_start"], "2026-10-16")
        self.assertEqual(row["date_stop"], "2026-10-16")

    def test_switching_precision_does_not_mutate_tasks(self):
        """Test H — hour→day→hour flips must leave every task datetime,
        dependency, baseline and variance untouched (BRD §20)."""
        project = self.env["project.project"].create({"name": "Flip"})
        task_a = self._make_task(
            project, "A",
            date_assign="2026-10-16 09:30:00",
            date_deadline="2026-10-18 17:45:00",
        )
        task_b = self._make_task(
            project, "B",
            date_assign="2026-10-19 08:15:00",
            date_deadline="2026-10-20 16:20:00",
            depend_on_ids=[(4, task_a.id)],
        )
        snapshot = {
            "a_start": task_a.date_assign,
            "a_stop": task_a.date_deadline,
            "b_start": task_b.date_assign,
            "b_stop": task_b.date_deadline,
            "deps": task_b.depend_on_ids.ids,
            "alloc": task_a.allocated_hours,
        }

        project.planning_precision = "day"
        self.assertEqual(task_a.date_assign, snapshot["a_start"])
        self.assertEqual(task_a.date_deadline, snapshot["a_stop"])
        self.assertEqual(task_b.date_assign, snapshot["b_start"])
        self.assertEqual(task_b.date_deadline, snapshot["b_stop"])
        self.assertEqual(task_b.depend_on_ids.ids, snapshot["deps"])

        project.planning_precision = "hour"
        self.assertEqual(task_a.date_assign, snapshot["a_start"])
        self.assertEqual(task_a.date_deadline, snapshot["a_stop"])
        self.assertEqual(task_b.date_assign, snapshot["b_start"])
        self.assertEqual(task_b.date_deadline, snapshot["b_stop"])
        self.assertEqual(task_b.depend_on_ids.ids, snapshot["deps"])
        self.assertEqual(task_a.allocated_hours, snapshot["alloc"])

    def test_project_isolation(self):
        """Test G — precision is strictly per project."""
        day = self.env["project.project"].create(
            {"name": "A", "planning_precision": "day"}
        )
        hour = self.env["project.project"].create({"name": "B"})
        day.planning_precision = "hour"
        self.assertEqual(hour.planning_precision, "hour")
        day.planning_precision = "day"
        self.assertEqual(hour.planning_precision, "hour")

    def test_dependency_scheduling_regression(self):
        """Test I — FS scheduling still drives the successor in a
        day-precision project; the engine is untouched."""
        project = self.env["project.project"].create(
            {"name": "Dep", "planning_precision": "day"}
        )
        pred = self._make_task(
            project, "Pred",
            date_assign="2026-10-16 09:00:00",
            date_deadline="2026-10-17 18:00:00",
        )
        succ = self._make_task(
            project, "Succ",
            date_assign="2026-10-18 09:00:00",
            date_deadline="2026-10-19 18:00:00",
            depend_on_ids=[(4, pred.id)],
        )
        # Push the predecessor's finish forward — the successor must move.
        pred.update_planner_task({
            "date_start": "2026-10-16",
            "date_stop": "2026-10-19",
            "duration_days": 4,
        })
        succ.invalidate_recordset()
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == succ.id
        )
        self.assertGreaterEqual(row["date_start"], "2026-10-20")

    def test_parent_rollup_regression(self):
        """Test J — parent start/end still roll up from children."""
        project = self.env["project.project"].create(
            {"name": "Rollup", "planning_precision": "day"}
        )
        parent = self._make_task(project, "Parent")
        self._make_task(
            project, "C1", parent_id=parent.id,
            date_assign="2026-10-16 09:00:00",
            date_deadline="2026-10-18 18:00:00",
        )
        self._make_task(
            project, "C2", parent_id=parent.id,
            date_assign="2026-10-20 09:00:00",
            date_deadline="2026-10-22 18:00:00",
        )
        rows = {
            r["id"]: r
            for r in project.get_planner_data()["tasks"]
        }
        self.assertLessEqual(rows[parent.id]["date_start"], "2026-10-16")
        self.assertGreaterEqual(rows[parent.id]["date_stop"], "2026-10-22")
