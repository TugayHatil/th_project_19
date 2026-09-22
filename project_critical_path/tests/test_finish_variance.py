# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestFinishVariance(TransactionCase):
    """Finish Variance Tail (BRD): date_done stamping, the stored
    finish_variance_state filter field and the planner payload values the
    tail renders from (own close for leaves, last child close for parents).

    The feature is read-only on top of scheduling — these tests only check
    the serialized data and the stamped fields, never the scheduler.
    """

    def _make_task(self, project, name, parent=None, **values):
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
            "parent_id": parent.id if parent else False,
            **values,
        })

    def _close(self, task, done_dt):
        """Close a task at an exact timestamp (the write() hook stamps
        date_done itself when no explicit value is given)."""
        task.write({"state": "1_done", "date_done": done_dt})

    def test_finish_variance_positive(self):
        """Plan 01.01 close 05.01 → late → red tail data."""
        project = self.env["project.project"].create({"name": "Late finish"})
        task = self._make_task(
            project, "Late task",
            date_assign="2026-12-29 09:00:00",
            date_deadline="2027-01-01 18:00:00",
        )

        self._close(task, "2027-01-05 18:00:00")

        self.assertEqual(task.finish_variance_state, "late")
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertTrue(row["is_done"])
        self.assertEqual(row["date_done"], "2027-01-05")
        self.assertTrue(row["dt_done"])

    def test_finish_variance_negative(self):
        """Plan 10.01 close 08.01 → early → green tail data."""
        project = self.env["project.project"].create({"name": "Early finish"})
        task = self._make_task(
            project, "Early task",
            date_assign="2027-01-05 09:00:00",
            date_deadline="2027-01-10 18:00:00",
        )

        self._close(task, "2027-01-08 18:00:00")

        self.assertEqual(task.finish_variance_state, "early")
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["date_done"], "2027-01-08")

    def test_finish_variance_zero(self):
        """Plan == actual → on_time → no tail."""
        project = self.env["project.project"].create({"name": "On time"})
        task = self._make_task(
            project, "Punctual task",
            date_assign="2026-12-29 09:00:00",
            date_deadline="2027-01-01 18:00:00",
        )

        self._close(task, "2027-01-01 18:00:00")

        self.assertEqual(task.finish_variance_state, "on_time")
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["date_done"], "2027-01-01")

    def test_finish_variance_open_task_has_no_state(self):
        """An open task never reports a variance state or close date."""
        project = self.env["project.project"].create({"name": "Open task"})
        task = self._make_task(
            project, "Running",
            date_assign="2027-01-01 09:00:00",
            date_deadline="2027-01-05 18:00:00",
        )

        self.assertFalse(task.date_done)
        self.assertFalse(task.finish_variance_state)
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertFalse(row["date_done"])
        self.assertFalse(row["dt_done"])

    def test_finish_variance_reopen_clears_close(self):
        """Reopening a done task clears date_done and the variance state."""
        project = self.env["project.project"].create({"name": "Reopen"})
        task = self._make_task(
            project, "Flapping",
            date_assign="2027-01-01 09:00:00",
            date_deadline="2027-01-05 18:00:00",
        )

        self._close(task, "2027-01-05 18:00:00")
        self.assertEqual(task.finish_variance_state, "on_time")

        task.state = "03_approved" if "03_approved" in dict(
            task._fields["state"].selection or []
        ) else "01_in_progress"
        self.assertFalse(task.date_done)
        self.assertFalse(task.finish_variance_state)

    def test_parent_finish_variance(self):
        """BRD §8: the parent's actual close is the LAST closed child —
        child 2.1 10→12 Jan (late), child 2.2 15→14 Jan (early); the parent
        planned 15 Jan closes effectively 14 Jan → −1 day (early)."""
        project = self.env["project.project"].create({"name": "Parent rollup"})
        parent = self._make_task(
            project, "Phase",
            date_assign="2027-01-10 09:00:00",
            date_deadline="2027-01-15 18:00:00",
        )
        child_a = self._make_task(
            project, "Child A", parent=parent,
            date_assign="2027-01-10 09:00:00",
            date_deadline="2027-01-10 18:00:00",
        )
        child_b = self._make_task(
            project, "Child B", parent=parent,
            date_assign="2027-01-11 09:00:00",
            date_deadline="2027-01-15 18:00:00",
        )

        self._close(child_a, "2027-01-12 18:00:00")
        # Parent has no effective close while a child is still open.
        self.assertFalse(parent._planner_effective_done())
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == parent.id
        )
        self.assertFalse(row["date_done"])

        self._close(child_b, "2027-01-14 18:00:00")
        self.assertEqual(
            parent._planner_effective_done().date().isoformat(), "2027-01-14"
        )
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == parent.id
        )
        self.assertEqual(row["date_done"], "2027-01-14")

    def test_day_scale_hour_precision(self):
        """The payload keeps hour precision in dt_done/dt_stop even though
        the variance itself is whole-day (BRD v2) — a same-day 18:00→22:00
        close is on time and shows no tail."""
        project = self.env["project.project"].create({"name": "Hour drift"})
        task = self._make_task(
            project, "Four hours later, same day",
            date_assign="2027-01-01 09:00:00",
            date_deadline="2027-01-01 18:00:00",
        )

        self._close(task, "2027-01-01 22:00:00")

        self.assertEqual(task.finish_variance_state, "on_time")
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        # dt_done is still serialized at minute precision — the day-based
        # rule lives in the variance, not the data.
        self.assertTrue(row["dt_done"].startswith("2027-01-01"))
        self.assertTrue(row["dt_done"].endswith("22:00"))
        self.assertTrue(row["dt_stop"].endswith("18:00"))

    def test_cross_midnight_close(self):
        """BRD Test 05: plan 23:00, close 02:00 next day — one calendar day
        late across the midnight boundary."""
        project = self.env["project.project"].create({"name": "Cross midnight"})
        task = self._make_task(
            project, "Overnight",
            date_assign="2027-01-01 09:00:00",
            date_deadline="2027-01-01 23:00:00",
        )

        self._close(task, "2027-01-02 02:00:00")

        self.assertEqual(task.finish_variance_state, "late")
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["date_done"], "2027-01-02")
        self.assertTrue(row["dt_done"].endswith("02:00"))

    def test_finish_variance_filters_searchable(self):
        """The three planner filters map to a real domain leaf on the
        stored finish_variance_state field."""
        project = self.env["project.project"].create({"name": "Filterable"})
        late = self._make_task(
            project, "Late",
            date_assign="2027-01-01 09:00:00",
            date_deadline="2027-01-01 18:00:00",
        )
        early = self._make_task(
            project, "Early",
            date_assign="2027-01-05 09:00:00",
            date_deadline="2027-01-10 18:00:00",
        )
        on_time = self._make_task(
            project, "OnTime",
            date_assign="2027-01-12 09:00:00",
            date_deadline="2027-01-15 18:00:00",
        )
        self._close(late, "2027-01-05 18:00:00")
        self._close(early, "2027-01-08 18:00:00")
        self._close(on_time, "2027-01-15 18:00:00")

        tasks = self.env["project.task"]
        self.assertEqual(
            tasks.search(
                [("project_id", "=", project.id),
                 ("finish_variance_state", "=", "late")]
            ), late
        )
        self.assertEqual(
            tasks.search(
                [("project_id", "=", project.id),
                 ("finish_variance_state", "=", "early")]
            ), early
        )
        self.assertEqual(
            tasks.search(
                [("project_id", "=", project.id),
                 ("finish_variance_state", "=", "on_time")]
            ), on_time
        )

    def test_planner_detail_serializes_done_fields(self):
        """The Inspector section reads is_done + date_done/dt_done from
        get_planner_detail — open tasks expose them as empty."""
        project = self.env["project.project"].create({"name": "Detail done"})
        task = self._make_task(
            project, "Inspectable",
            date_assign="2027-01-01 09:00:00",
            date_deadline="2027-01-01 18:00:00",
        )

        detail = task.get_planner_detail()["task"]
        self.assertFalse(detail["is_done"])
        self.assertFalse(detail["date_done"])

        self._close(task, "2027-01-01 22:00:00")
        detail = task.get_planner_detail()["task"]
        self.assertTrue(detail["is_done"])
        self.assertEqual(detail["date_done"], "2027-01-01")
        self.assertTrue(detail["dt_done"].endswith("22:00"))
