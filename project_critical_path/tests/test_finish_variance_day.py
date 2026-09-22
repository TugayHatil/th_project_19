# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestFinishVarianceDay(TransactionCase):
    """Finish Variance Flag v2 (BRD): the variance is calendar-day based —
    date(date_done) - date(date_stop). Hours never count: a 22:00 close
    against an 18:00 plan on the same day is still on time.
    """

    def _make_task(self, project, name, parent=None, **values):
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
            "parent_id": parent.id if parent else False,
            **values,
        })

    def _close(self, task, done_dt):
        task.write({"state": "1_done", "date_done": done_dt})

    def test_finish_variance_day_positive(self):
        """Plan 24, close 26 → +2 days → late."""
        project = self.env["project.project"].create({"name": "Day+"})
        task = self._make_task(
            project, "Task",
            date_assign="2027-01-20 09:00:00",
            date_deadline="2027-01-24 18:00:00",
        )

        self._close(task, "2027-01-26 18:00:00")

        self.assertEqual(task.finish_variance_state, "late")
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["date_stop"], "2027-01-24")
        self.assertEqual(row["date_done"], "2027-01-26")

    def test_finish_variance_day_negative(self):
        """Plan 24, close 22 → −2 days → early."""
        project = self.env["project.project"].create({"name": "Day-"})
        task = self._make_task(
            project, "Task",
            date_assign="2027-01-20 09:00:00",
            date_deadline="2027-01-24 18:00:00",
        )

        self._close(task, "2027-01-22 18:00:00")

        self.assertEqual(task.finish_variance_state, "early")
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["date_done"], "2027-01-22")

    def test_finish_variance_same_day_zero(self):
        """Plan 24, close 24 → 0 → on_time, no tail."""
        project = self.env["project.project"].create({"name": "Day0"})
        task = self._make_task(
            project, "Task",
            date_assign="2027-01-20 09:00:00",
            date_deadline="2027-01-24 18:00:00",
        )

        self._close(task, "2027-01-24 18:00:00")

        self.assertEqual(task.finish_variance_state, "on_time")

    def test_finish_variance_ignore_hours(self):
        """BRD v2 Test 04-05: hours never count. 08:00→22:00 same day is
        still on time; 23:00→01:00 next day is one day late."""
        project = self.env["project.project"].create({"name": "Hours ignored"})
        same_day = self._make_task(
            project, "Same day",
            date_assign="2027-01-24 08:00:00",
            date_deadline="2027-01-24 18:00:00",
        )
        overnight = self._make_task(
            project, "Overnight",
            date_assign="2027-01-24 08:00:00",
            date_deadline="2027-01-24 23:00:00",
        )

        self._close(same_day, "2027-01-24 22:00:00")
        self._close(overnight, "2027-01-25 01:00:00")

        self.assertEqual(same_day.finish_variance_state, "on_time")
        self.assertEqual(overnight.finish_variance_state, "late")
        row = next(
            r for r in project.get_planner_data()["tasks"]
            if r["id"] == overnight.id
        )
        self.assertEqual(row["date_done"], "2027-01-25")

    def test_mechanical_design_example(self):
        """BRD v2 §4 — the mandatory regression anchor: a task planned to
        finish on the 24th that actually closed on the 26th must report
        exactly +2 days (never +1/+3 from hour drift)."""
        project = self.env["project.project"].create({"name": "MD anchor"})
        task = self._make_task(
            project, "Mechanical Design",
            date_assign="2027-01-19 09:00:00",
            date_deadline="2027-01-24 18:00:00",
        )

        self._close(task, "2027-01-26 10:00:00")  # hour must not matter

        self.assertEqual(task.finish_variance_state, "late")
        row = next(
            r for r in project.get_planner_data()["tasks"] if r["id"] == task.id
        )
        self.assertEqual(row["date_stop"], "2027-01-24")
        self.assertEqual(row["date_done"], "2027-01-26")
        # The day diff the +2g flag renders from:
        from datetime import date
        self.assertEqual(
            (date(2027, 1, 26) - date(2027, 1, 24)).days, 2
        )
