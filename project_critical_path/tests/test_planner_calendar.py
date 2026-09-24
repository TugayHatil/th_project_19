# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestPlannerCalendar(TransactionCase):
    """BRD Working Calendar — the project-level resource.calendar drives
    the planner's folded non-working-time timeline. The payload carries
    raw attendances + leaves once (no N+1); the scheduling engine and
    task datetimes are never touched by calendar changes.
    """

    def _make_calendar(self, name, hours=(9.0, 13.0, 14.0, 18.0), weekdays="01234"):
        calendar = self.env["resource.calendar"].create({
            "name": name,
            "hours_per_day": 8.0,
        })
        calendar.attendance_ids.unlink()
        self.env["resource.calendar.attendance"].create([
            {
                "name": "%s %s" % (name, part),
                "calendar_id": calendar.id,
                "dayofweek": day,
                "hour_from": hours[i * 2],
                "hour_to": hours[i * 2 + 1],
                "day_period": part,
            }
            for day in weekdays
            for i, part in enumerate(("morning", "afternoon"))
        ])
        return calendar

    def _make_project(self, name, calendar=None):
        return self.env["project.project"].create({
            "name": name,
            "resource_calendar_id": calendar.id if calendar else False,
        })

    def test_calendar_assignable(self):
        """Test 01 — the project accepts an Odoo resource.calendar."""
        calendar = self._make_calendar("Cal A")
        project = self._make_project("Proj", calendar)
        self.assertEqual(project.resource_calendar_id, calendar)

    def test_payload_carries_calendar(self):
        """Test 02 — planner payload exposes the selected calendar."""
        calendar = self._make_calendar("Cal B")
        project = self._make_project("Proj B", calendar)
        payload = project.get_planner_data()["project"]["calendar"]
        self.assertEqual(payload["id"], calendar.id)
        self.assertTrue(payload["tz"])
        self.assertEqual(payload["hoursPerDay"], 8.0)

    def test_working_intervals(self):
        """Test 03 — attendances serialize as weekday/hour intervals."""
        calendar = self._make_calendar("Cal C", (9.0, 13.0, 14.0, 18.0))
        payload = self._make_project("Proj C", calendar) \
            .get_planner_data()["project"]["calendar"]
        monday = [a for a in payload["attendances"] if a["weekday"] == 0]
        self.assertEqual(
            [(a["from"], a["to"]) for a in monday],
            [(9.0, 13.0), (14.0, 18.0)],
        )

    def test_lunch_is_not_working(self):
        """Test 04 — lunch attendances are excluded so the lunch hour
        falls inside an intra-day gap on the frontend."""
        calendar = self._make_calendar("Cal D", (9.0, 13.0, 14.0, 18.0))
        self.env["resource.calendar.attendance"].create({
            "name": "Lunch",
            "calendar_id": calendar.id,
            "dayofweek": "0",
            "hour_from": 13.0,
            "hour_to": 14.0,
            "day_period": "lunch",
        })
        payload = self._make_project("Proj D", calendar) \
            .get_planner_data()["project"]["calendar"]
        monday = [a for a in payload["attendances"] if a["weekday"] == 0]
        self.assertEqual(len(monday), 2)
        self.assertNotIn((13.0, 14.0), [(a["from"], a["to"]) for a in monday])

    def test_weekend_has_no_attendance(self):
        """Test 05 — no attendance rows for Saturday/Sunday."""
        calendar = self._make_calendar("Cal E")
        payload = self._make_project("Proj E", calendar) \
            .get_planner_data()["project"]["calendar"]
        weekend = [a for a in payload["attendances"] if a["weekday"] in (5, 6)]
        self.assertFalse(weekend)

    def test_full_day_leave_is_sent(self):
        """Test 06 — a calendar-wide leave reaches the payload so the
        frontend renders the covered day as a full off day."""
        calendar = self._make_calendar("Cal F")
        self.env["resource.calendar.leaves"].create({
            "name": "Company holiday",
            "calendar_id": calendar.id,
            "date_from": "2027-01-01 00:00:00",
            "date_to": "2027-01-01 23:59:59",
        })
        payload = self._make_project("Proj F", calendar) \
            .get_planner_data()["project"]["calendar"]
        self.assertEqual(len(payload["leaves"]), 1)
        self.assertEqual(payload["leaves"][0]["from"], "2027-01-01 00:00:00")

    def test_calendar_change_reflects_payload(self):
        """Test 07 — switching the project calendar is reflected in the
        next payload (no stale cache server-side)."""
        cal_a = self._make_calendar("Cal G1")
        cal_b = self._make_calendar("Cal G2", (8.0, 12.0, 13.0, 17.0))
        project = self._make_project("Proj G", cal_a)
        self.assertEqual(
            project.get_planner_data()["project"]["calendar"]["id"], cal_a.id
        )
        project.resource_calendar_id = cal_b
        payload = project.get_planner_data()["project"]["calendar"]
        self.assertEqual(payload["id"], cal_b.id)
        self.assertEqual(payload["attendances"][0]["from"], 8.0)

    def test_calendar_change_keeps_task_dates(self):
        """Test 08 — changing the calendar must never mutate task
        datetimes (the fold is visual only)."""
        cal_a = self._make_calendar("Cal H1")
        cal_b = self._make_calendar("Cal H2", (10.0, 12.0, 13.0, 19.0))
        project = self._make_project("Proj H", cal_a)
        task = self.env["project.task"].create({
            "name": "Stable",
            "project_id": project.id,
            "date_assign": "2027-01-04 09:00:00",
            "date_deadline": "2027-01-05 18:00:00",
        })
        start, stop = task.date_assign, task.date_deadline
        project.resource_calendar_id = cal_b
        self.assertEqual((task.date_assign, task.date_deadline), (start, stop))

    def test_no_calendar_means_no_fold_data(self):
        """Backward compatibility — an empty calendar field serializes
        False so the timeline stays continuous/uncompressed."""
        project = self.env["project.project"].create({
            "name": "No cal",
            "resource_calendar_id": False,
        })
        self.assertFalse(
            project.get_planner_data()["project"]["calendar"]
        )
