# -*- coding: utf-8 -*-

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestActualTracking(TransactionCase):
    """BRD TEST-ACT-001..005 + actual-status/finish-resolution coverage."""

    def _make_task(self, project, name, **values):
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
            **values,
        })

    def test_act_001_planned_dates_stored(self):
        """TEST-ACT-001 — planned start/end land on the task unchanged."""
        project = self.env["project.project"].create({"name": "ACT-001"})
        task = self._make_task(
            project, "Task",
            date_assign="2027-01-20 09:00:00",
            date_deadline="2027-01-24 18:00:00",
        )
        self.assertEqual(str(task.date_assign), "2027-01-20 09:00:00")
        self.assertEqual(str(task.date_deadline), "2027-01-24 18:00:00")

    def test_act_002_actual_duration_same_day(self):
        """TEST-ACT-002 — a same-day actual window is its real hour span."""
        project = self.env["project.project"].create({"name": "ACT-002a"})
        task = self._make_task(
            project, "Task",
            date_actual_start="2027-01-20 09:00:00",
            date_actual_end="2027-01-20 14:30:00",
        )
        self.assertAlmostEqual(task.actual_duration, 5.5, places=2)

    def test_act_002_actual_duration_multi_day(self):
        """TEST-ACT-002 — multi-day windows follow the planner convention:
        inclusive day-count x calendar hours-per-day (8h fallback)."""
        project = self.env["project.project"].create({"name": "ACT-002b"})
        task = self._make_task(
            project, "Task",
            date_actual_start="2027-01-20 09:00:00",
            date_actual_end="2027-01-22 18:00:00",
        )
        self.assertAlmostEqual(task.actual_duration, 24.0, places=2)

    def test_act_003_actual_end_after_planned_is_late(self):
        """TEST-ACT-003 — actual finish 2 days after deadline → +2 / late."""
        project = self.env["project.project"].create({"name": "ACT-003"})
        task = self._make_task(
            project, "Task",
            date_deadline="2027-01-24 18:00:00",
            date_actual_start="2027-01-20 09:00:00",
            date_actual_end="2027-01-26 10:00:00",
        )
        self.assertEqual(task.schedule_variance_days, 2)
        self.assertEqual(task.schedule_variance_state, "late")

    def test_act_004_actual_end_equal_planned_zero_variance(self):
        """TEST-ACT-004 — same calendar day → variance 0 / on_time,
        hours never count."""
        project = self.env["project.project"].create({"name": "ACT-004"})
        task = self._make_task(
            project, "Task",
            date_deadline="2027-01-24 18:00:00",
            date_actual_start="2027-01-24 08:00:00",
            date_actual_end="2027-01-24 22:30:00",
        )
        self.assertEqual(task.schedule_variance_days, 0)
        self.assertEqual(task.schedule_variance_state, "on_time")

    def test_act_005_actual_end_before_planned_is_early(self):
        """TEST-ACT-005 — finishing early must not look delayed."""
        project = self.env["project.project"].create({"name": "ACT-005"})
        task = self._make_task(
            project, "Task",
            date_deadline="2027-01-24 18:00:00",
            date_actual_start="2027-01-20 09:00:00",
            date_actual_end="2027-01-22 18:00:00",
        )
        self.assertEqual(task.schedule_variance_days, -2)
        self.assertEqual(task.schedule_variance_state, "early")
        self.assertFalse(task.schedule_variance_days > 0)

    def test_no_actual_data_no_duration(self):
        """BRD §28 — untouched actuals produce no duration/variance."""
        project = self.env["project.project"].create({"name": "Empty"})
        task = self._make_task(
            project, "Task",
            date_assign="2027-01-20 09:00:00",
            date_deadline="2027-01-24 18:00:00",
        )
        self.assertFalse(task.actual_finish)
        self.assertEqual(task.actual_duration, 0.0)
        self.assertFalse(task.schedule_variance_state)
        self.assertFalse(task.schedule_variance_days)
        self.assertEqual(task.actual_status, "not_started")

    def test_actual_end_before_start_rejected(self):
        """BRD §28 — Actual End < Actual Start is a ValidationError."""
        project = self.env["project.project"].create({"name": "Bad range"})
        with self.assertRaises(ValidationError):
            self._make_task(
                project, "Task",
                date_actual_start="2027-01-24 09:00:00",
                date_actual_end="2027-01-20 18:00:00",
            )

    def test_actual_status_transitions(self):
        """not_started → in_progress (manual start) → done (manual end)."""
        project = self.env["project.project"].create({"name": "Status"})
        task = self._make_task(project, "Task")
        self.assertEqual(task.actual_status, "not_started")

        task.date_actual_start = "2027-01-20 09:00:00"
        self.assertEqual(task.actual_status, "in_progress")

        task.date_actual_end = "2027-01-22 18:00:00"
        self.assertEqual(task.actual_status, "done")

    def test_actual_status_timesheet_counts_as_started(self):
        """A task with booked hours but no manual start is in progress."""
        project = self.env["project.project"].create({"name": "TS start"})
        task = self._make_task(project, "Task")
        employee = self.env["hr.employee"].create({"name": "TS Emp"})
        self.env["account.analytic.line"].create({
            "name": "Work",
            "project_id": project.id,
            "task_id": task.id,
            "employee_id": employee.id,
            "unit_amount": 2.0,
        })
        task.invalidate_recordset(["effective_hours"])
        self.assertEqual(task.actual_status, "in_progress")

    def test_actual_finish_resolution(self):
        """Effective finish: manual entry wins over the done stamp; the
        stamp is the fallback while no manual end exists."""
        project = self.env["project.project"].create({"name": "Finish"})
        task = self._make_task(project, "Task")

        # Done stamp alone drives the effective finish.
        task.write({"state": "1_done", "date_done": "2027-01-24 17:00:00"})
        self.assertEqual(str(task.actual_finish), "2027-01-24 17:00:00")

        # Manual entry takes precedence.
        task.date_actual_end = "2027-01-25 12:00:00"
        self.assertEqual(str(task.actual_finish), "2027-01-25 12:00:00")

        # Clearing the manual entry falls back to the stamp.
        task.date_actual_end = False
        self.assertEqual(str(task.actual_finish), "2027-01-24 17:00:00")

    def test_planner_payload_actual_keys(self):
        """get_planner_data rows carry the serialized actual block."""
        project = self.env["project.project"].create({"name": "Payload"})
        task = self._make_task(
            project, "Task",
            date_assign="2027-01-20 09:00:00",
            date_deadline="2027-01-22 18:00:00",
            date_actual_start="2027-01-21 09:00:00",
            date_actual_end="2027-01-23 18:00:00",
        )
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["actual_start"], "2027-01-21")
        self.assertEqual(row["actual_end"], "2027-01-23")
        self.assertEqual(row["actual_status"], "done")
        self.assertEqual(row["schedule_variance_state"], "late")
        self.assertEqual(row["schedule_variance_days"], 1)
        self.assertAlmostEqual(row["actual_duration"], 16.0, places=1)

    def test_get_planner_detail_actual_block(self):
        project = self.env["project.project"].create({"name": "Detail"})
        task = self._make_task(
            project, "Task",
            date_actual_start="2027-01-21 09:00:00",
        )
        detail = task.get_planner_detail()
        self.assertIn("actual", detail)
        self.assertEqual(detail["actual"]["date_start"], "2027-01-21")
        self.assertEqual(detail["actual"]["status"], "in_progress")


class TestProjectActualSummary(TransactionCase):
    """BRD §5 — project-level KPI aggregation."""

    def test_project_kpis(self):
        project = self.env["project.project"].create({"name": "KPI"})
        task_done = self.env["project.task"].create({
            "name": "Done", "project_id": project.id,
            "date_assign": "2027-01-19 09:00:00",
            "date_deadline": "2027-01-20 18:00:00",
            "date_actual_start": "2027-01-19 09:00:00",
            "date_actual_end": "2027-01-22 18:00:00",
            "allocated_hours": 16.0,
            "progress": 1.0,
        })
        task_open = self.env["project.task"].create({
            "name": "Open", "project_id": project.id,
            "date_assign": "2027-01-19 09:00:00",
            "date_deadline": "2027-01-21 18:00:00",
            "allocated_hours": 16.0,
            "progress": 0.5,
        })
        task_new = self.env["project.task"].create({
            "name": "New", "project_id": project.id,
            "allocated_hours": 8.0,
        })
        project.invalidate_recordset()

        self.assertEqual(project.actual_task_count, 3)
        self.assertEqual(project.actual_done_task_count, 1)
        self.assertEqual(project.actual_in_progress_task_count, 0)
        self.assertEqual(project.actual_not_started_task_count, 2)
        # Weighted completion: (16*1 + 16*0.5 + 8*0) / 40 = 60 %
        self.assertAlmostEqual(project.actual_completion, 60.0, places=1)
        # Actual span: 19 Jan 09:00 → 22 Jan 18:00 = 81 h
        self.assertAlmostEqual(project.actual_span_hours, 81.0, places=1)
        # Latest actual finish 22 Jan vs latest deadline 21 Jan → +1
        self.assertEqual(project.actual_finish_variance_days, 1)
        self.assertEqual(project.actual_delayed_task_count, 1)
        self.assertEqual(project.actual_critical_delayed_task_count, 0)

    def test_project_kpis_empty(self):
        project = self.env["project.project"].create({"name": "Empty KPI"})
        project.invalidate_recordset()
        self.assertEqual(project.actual_task_count, 0)
        self.assertEqual(project.actual_completion, 0.0)
        self.assertEqual(project.actual_span_hours, 0.0)
        self.assertFalse(project.actual_finish_variance_days)

    def test_project_completion_hours_fallback(self):
        """No allocated hours → plain average, same as the WBS rollup."""
        project = self.env["project.project"].create({"name": "Avg"})
        self.env["project.task"].create({
            "name": "A", "project_id": project.id, "progress": 0.5,
        })
        self.env["project.task"].create({
            "name": "B", "project_id": project.id, "progress": 1.0,
        })
        project.invalidate_recordset()
        self.assertAlmostEqual(project.actual_completion, 75.0, places=1)
