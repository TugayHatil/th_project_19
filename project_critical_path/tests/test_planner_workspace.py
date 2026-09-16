# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestPlannerWorkspace(TransactionCase):
    """Planner Workspace data API: WBS ordering, dates, hierarchy flags."""

    def _make_task(self, project, name, parent=None, **values):
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
            "parent_id": parent.id if parent else False,
            **values,
        })

    def test_planner_data_returns_tasks_in_wbs_order(self):
        project = self.env["project.project"].create({"name": "Planner order"})
        eng = self._make_task(project, "Engineering",
                              date_assign="2026-03-01 09:00:00", date_deadline="2026-03-31 18:00:00")
        drawing = self._make_task(project, "Drawing", parent=eng,
                                  date_assign="2026-03-01 09:00:00", date_deadline="2026-03-10 18:00:00")
        detail = self._make_task(project, "Detail Drawing", parent=drawing,
                                 date_assign="2026-03-02 09:00:00", date_deadline="2026-03-06 18:00:00")
        approval = self._make_task(project, "Approval", parent=eng,
                                   date_assign="2026-03-11 09:00:00", date_deadline="2026-03-17 18:00:00")
        procurement = self._make_task(project, "Procurement",
                                      date_assign="2026-04-01 09:00:00", date_deadline="2026-04-10 18:00:00")

        data = project.get_planner_data()

        self.assertEqual(data["project"]["id"], project.id)
        rows = {row["wbs_code"]: row for row in data["tasks"]}
        self.assertEqual([row["wbs_code"] for row in data["tasks"]], ["1", "1.1", "1.1.1", "1.2", "2"])
        self.assertEqual(rows["1"]["name"], "Engineering")
        self.assertTrue(rows["1"]["has_children"])
        self.assertTrue(rows["1.1"]["has_children"])
        self.assertFalse(rows["1.1.1"]["has_children"])
        self.assertEqual(rows["1.1.1"]["parent_id"], drawing.id)
        self.assertEqual(rows["1.2"]["parent_id"], eng.id)
        self.assertFalse(rows["2"]["parent_id"])
        self.assertEqual(rows["1.1.1"]["wbs_level"], 3)
        self.assertEqual(rows["1"]["date_start"], "2026-03-01")
        self.assertEqual(rows["1"]["date_stop"], "2026-03-31")
        self.assertEqual(rows["2"]["date_stop"], "2026-04-10")

    def test_planner_data_includes_is_critical_flag(self):
        project = self.env["project.project"].create({"name": "CP flag"})
        first = self._make_task(project, "Long chain start", allocated_hours=8.0)
        self._make_task(
            project, "Long chain end", allocated_hours=8.0,
            depend_on_ids=[(4, first.id)],
        )
        # A shorter parallel chain has slack, so it is not on the critical path.
        short = self._make_task(project, "Short parallel", allocated_hours=4.0)

        rows = {row["name"]: row for row in project.get_planner_data()["tasks"]}

        self.assertTrue(rows["Long chain start"]["is_critical"])
        self.assertTrue(rows["Long chain end"]["is_critical"])
        self.assertFalse(rows["Short parallel"]["is_critical"])
        # dependency edges feed the Gantt FS arrows
        self.assertEqual(
            rows["Long chain end"]["depend_on_ids"], [rows["Long chain start"]["id"]],
        )
        self.assertEqual(rows["Long chain start"]["depend_on_ids"], [])

    def test_planner_data_serializes_missing_dates_as_false(self):
        project = self.env["project.project"].create({"name": "Undated planner"})
        self._make_task(project, "No dates task")

        row = project.get_planner_data()["tasks"][0]

        self.assertFalse(row["date_start"])
        self.assertFalse(row["date_stop"])

    def test_action_open_planner_workspace_returns_client_action(self):
        project = self.env["project.project"].create({"name": "Planner action"})

        action = project.action_open_planner_workspace()

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "project_critical_path.planner_workspace")
        self.assertEqual(action["params"]["project_id"], project.id)

    def test_get_planner_projects_lists_projects(self):
        project = self.env["project.project"].create({"name": "Listed project"})

        projects = self.env["project.project"].get_planner_projects()

        self.assertIn(
            {"id": project.id, "name": project.display_name},
            [{"id": entry["id"], "name": entry["name"]} for entry in projects],
        )

    def test_get_planner_detail_returns_editable_fields_and_options(self):
        project = self.env["project.project"].create({"name": "Inspector detail"})
        first = self._make_task(
            project, "Drawing",
            date_assign="2026-03-01 09:00:00", date_deadline="2026-03-10 18:00:00",
        )
        second = self._make_task(
            project, "Approval",
            date_assign="2026-03-11 09:00:00", date_deadline="2026-03-15 18:00:00",
            depend_on_ids=[(4, first.id)],
        )

        detail = second.get_planner_detail()
        task = detail["task"]

        self.assertEqual(task["id"], second.id)
        self.assertEqual(task["name"], "Approval")
        self.assertEqual(task["date_start"], "2026-03-11")
        self.assertEqual(task["date_stop"], "2026-03-15")
        self.assertEqual(task["depend_on_ids"], [first.id])
        self.assertNotIn(first.id, task["dependent_ids"])
        self.assertIn("progress", task)
        self.assertIn("critical_slack", task)
        self.assertIn("allocated_hours", task)
        self.assertIn("effective_hours", task)
        self.assertTrue(detail["options"]["users"], "users dropdown should not be empty")

        # Progress is serialized as 0..100 for the inspector
        self.assertGreaterEqual(task["progress"], 0)
        self.assertLessEqual(task["progress"], 100)

    def test_update_planner_task_writes_inspector_fields(self):
        project = self.env["project.project"].create({"name": "Inspector update"})
        first = self._make_task(project, "Drawing")
        second = self._make_task(project, "Approval")
        stage = self.env["project.task.type"].create(
            {"name": "In Progress", "project_ids": [(4, project.id)]}
        )

        second.update_planner_task({
            "name": "Approval v2",
            "date_start": "2026-03-11",
            "date_stop": "2026-03-15",
            "duration_days": 5,
            "progress": 45,
            "stage_id": stage.id,
            "user_ids": [self.env.user.id],
            "depend_on_ids": [first.id],
            "dependent_ids": [],
        })

        self.assertEqual(second.name, "Approval v2")
        self.assertEqual(second.stage_id, stage)
        self.assertEqual(second.user_ids, self.env.user)
        self.assertEqual(second.depend_on_ids, first)
        self.assertAlmostEqual(second.progress, 0.45, places=2)
        # Dates round-trip through user timezone without shifting the day
        detail = second.get_planner_detail()["task"]
        self.assertEqual(detail["date_start"], "2026-03-11")
        self.assertEqual(detail["date_stop"], "2026-03-15")
        # A duration change syncs allocated_hours, which the critical path,
        # delay-impact and baseline comparisons all read.
        from odoo.addons.project_critical_path.models.project_planner import (
            _planner_hours_per_day,
        )
        self.assertAlmostEqual(
            second.allocated_hours, 5 * _planner_hours_per_day(second), places=2,
        )

    def test_update_planner_task_keeps_allocated_hours_when_duration_unchanged(self):
        project = self.env["project.project"].create({"name": "No clobber"})
        task = self._make_task(
            project, "Dated task",
            date_assign="2026-03-01 09:00:00", date_deadline="2026-03-11 18:00:00",
            allocated_hours=16.0,
        )

        # The form always sends the current dates and duration; unchanged
        # values must not overwrite an independently-set allocated_hours.
        task.update_planner_task({
            "name": "Renamed only",
            "date_start": "2026-03-01",
            "date_stop": "2026-03-11",
            "duration_days": 11,  # inclusive span 2026-03-01 → 2026-03-11
        })

        self.assertAlmostEqual(task.allocated_hours, 16.0, places=2)

    def test_update_planner_task_explicit_allocated_hours_wins_over_span(self):
        """The inspector edits duration in hours: an explicit allocated_hours
        is authoritative even when the day span would derive a different
        value (fractional-day effort like 20 h over a 9-day window)."""
        project = self.env["project.project"].create({"name": "Hour duration"})
        task = self._make_task(
            project, "Effort",
            date_assign="2026-03-01 09:00:00", date_deadline="2026-03-05 18:00:00",
            allocated_hours=16.0,
        )

        task.update_planner_task({
            "date_start": "2026-03-01",
            "date_stop": "2026-03-09",
            "duration_days": 9,
            "allocated_hours": 20.0,
        })

        self.assertAlmostEqual(task.allocated_hours, 20.0, places=2)

    def test_get_planner_detail_exposes_hours_per_day(self):
        """The inspector converts between hours and day spans client-side."""
        project = self.env["project.project"].create({"name": "Hours per day"})
        task = self._make_task(project, "Task")

        detail = task.get_planner_detail()["task"]

        self.assertGreater(detail["hours_per_day"], 0)
        self.assertIn("allocated_hours", detail)

    def test_update_planner_task_move_preserves_duration_and_time(self):
        """A bar move shifts both dates, keeps duration, allocated_hours and
        the stored time-of-day (drags must not reset hours)."""
        project = self.env["project.project"].create({"name": "Bar move"})
        task = self._make_task(
            project, "Movable",
            date_assign="2026-03-01 09:00:00", date_deadline="2026-03-11 18:00:00",
            allocated_hours=16.0,
        )

        task.update_planner_task({
            "date_start": "2026-03-03",
            "date_stop": "2026-03-13",
            "duration_days": 11,  # same inclusive span as before -> a move
        })

        detail = task.get_planner_detail()["task"]
        self.assertEqual(detail["date_start"], "2026-03-03")
        self.assertEqual(detail["date_stop"], "2026-03-13")
        self.assertAlmostEqual(task.allocated_hours, 16.0, places=2)
        self.assertEqual(task.date_assign.hour, 9)
        self.assertEqual(task.date_deadline.hour, 18)

    def test_planner_baseline_history_lists_versions_newest_first(self):
        project = self.env["project.project"].create({"name": "History list"})
        task = self._make_task(project, "Evolving task", allocated_hours=8.0)
        project.action_create_critical_path_baseline()
        task.allocated_hours = 11.0
        project.action_create_critical_path_baseline()

        history = project.get_planner_baseline_history()

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["name"], "v1.1")
        self.assertEqual(history[1]["name"], "v1.0")
        self.assertFalse(history[0]["is_initial"])
        self.assertTrue(history[1]["is_initial"])
        self.assertEqual(history[0]["previous_name"], "v1.0")
        self.assertEqual(
            history[0]["duration_variance"],
            history[0]["project_duration"] - history[1]["project_duration"],
        )

    def test_planner_baseline_summary_reports_task_changes(self):
        project = self.env["project.project"].create({"name": "Change summary"})
        stable = self._make_task(project, "Stable task", allocated_hours=5.0)
        growing = self._make_task(project, "Growing task", allocated_hours=8.0)
        project.action_create_critical_path_baseline()
        growing.allocated_hours = 11.0
        project.action_create_critical_path_baseline()
        latest = project.critical_path_baseline_ids[0]

        summary = project.get_planner_baseline_summary(latest.id)

        self.assertEqual(summary["name"], "v1.1")
        self.assertEqual(summary["previous_name"], "v1.0")
        change = next(
            item for item in summary["changes"] if item["task_id"] == growing.id
        )
        self.assertAlmostEqual(change["delta_hours"], 3.0)
        self.assertAlmostEqual(change["old_hours"], 8.0)
        self.assertAlmostEqual(change["new_hours"], 11.0)
        # Unchanged tasks are not reported as changes.
        self.assertFalse(
            any(item["task_id"] == stable.id for item in summary["changes"])
        )

    def test_planner_baseline_summary_initial_has_no_changes(self):
        project = self.env["project.project"].create({"name": "Initial summary"})
        self._make_task(project, "First task", allocated_hours=8.0)
        project.action_create_critical_path_baseline()
        baseline = project.critical_path_baseline_ids[0]

        summary = project.get_planner_baseline_summary(baseline.id)

        self.assertTrue(summary["is_initial"])
        self.assertEqual(summary["changes"], [])
        self.assertEqual(summary["tasks_changed"], 0)

    def test_planner_data_baseline_override_uses_historical_snapshot(self):
        project = self.env["project.project"].create({"name": "Compare override"})
        task = self._make_task(
            project, "Shifting task",
            date_assign="2026-03-01 09:00:00", date_deadline="2026-03-05 18:00:00",
        )
        project.action_create_critical_path_baseline()
        first = project.critical_path_baseline_ids[0]
        task.date_assign = "2026-03-10 09:00:00"
        task.date_deadline = "2026-03-14 18:00:00"
        project.action_create_critical_path_baseline()

        data = project.get_planner_data(baseline_id=first.id)
        row = next(item for item in data["tasks"] if item["id"] == task.id)

        self.assertEqual(row["baseline_name"], "v1.0")
        self.assertEqual(row["baseline_start"], "2026-03-01")
        self.assertEqual(row["baseline_stop"], "2026-03-05")

    def test_planner_data_serializes_hours_and_progress(self):
        """The bar-side info text reads Odoo's planned/timesheet/progress
        fields — Planner adds no duplicate calculation."""
        project = self.env["project.project"].create({"name": "Bar info"})
        task = self._make_task(project, "Tracked task", allocated_hours=10.0)

        row = next(
            item for item in project.get_planner_data()["tasks"]
            if item["id"] == task.id
        )

        self.assertAlmostEqual(row["allocated_hours"], 10.0)
        self.assertEqual(row["effective_hours"], 0.0)  # no timesheets yet
        self.assertIn("progress", row)

    def test_planner_resources_requirement_and_assignment_flow(self):
        """Planner resource APIs wrap the existing requirement/assignment
        models — create, assign, summarize and unassign."""
        project = self.env["project.project"].create({"name": "Planner resources"})
        task = self._make_task(
            project, "Resourced task",
            date_assign="2026-03-02 09:00:00", date_deadline="2026-03-06 18:00:00",
        )
        role = self.env["project.resource.role"].create(
            {"name": "Formen", "category": "human"}
        )
        employee = self.env["hr.employee"].create(
            {"name": "Ahmet Yilmaz", "resource_role_ids": [(4, role.id)]}
        )

        task.planner_save_requirement({
            "role_id": role.id, "quantity": 2, "planned_hours": 80.0,
        })
        res = task.get_planner_resources()
        self.assertEqual(len(res["requirements"]), 1)
        req = res["requirements"][0]
        self.assertEqual(req["status"], "waiting")
        self.assertEqual(req["assigned_quantity"], 0)
        # Requirement dates default to the task dates via the create hook.
        self.assertEqual(req["date_start"], "2026-03-02")
        self.assertEqual(req["date_end"], "2026-03-06")

        options_data = task.planner_get_assignment_options(req["id"])
        self.assertTrue(
            any(
                opt["employee_id"] == employee.id
                for opt in options_data["options"]
            )
        )
        # The timeline window wraps the requirement dates with context days.
        self.assertEqual(options_data["required"]["start"], "2026-03-02")
        self.assertEqual(options_data["required"]["end"], "2026-03-06")
        self.assertEqual(options_data["window"]["start"], "2026-02-28")
        self.assertEqual(options_data["window"]["end"], "2026-03-08")

        # The workspace lets the user narrow the assignment inside the
        # requirement range and previews its calendar-hours cost.
        hours = task.planner_estimate_assignment_hours(
            req["id"], employee_id=employee.id,
            date_start="2026-03-02", date_end="2026-03-03",
        )
        self.assertGreater(hours, 0)

        task.planner_assign_resource(
            req["id"], employee_id=employee.id,
            date_start="2026-03-02", date_end="2026-03-04",
        )
        req = task.get_planner_resources()["requirements"][0]
        self.assertEqual(req["assigned_quantity"], 1)
        self.assertEqual(req["status"], "partial")  # 1 of 2 assigned
        self.assertEqual(req["assignments"][0]["name"], "Ahmet Yilmaz")

        # Timeline payloads carry ids, ownership flags and datetimes, and
        # the window can be overridden for navigation.
        options2 = task.planner_get_assignment_options(
            req["id"], window_start="2026-03-01", window_end="2026-03-10",
        )
        emp_opt = next(
            opt for opt in options2["options"]
            if opt["employee_id"] == employee.id
        )
        mine = [item for item in emp_opt["schedule"] if item["mine"]]
        self.assertEqual(len(mine), 1)
        self.assertTrue(mine[0]["id"])
        self.assertEqual(mine[0]["date_start"], "2026-03-02")
        self.assertIn(":", mine[0]["dt_start"])

        # Timeline move/resize writes through the same constraints.
        asg_id = mine[0]["id"]
        task.planner_update_assignment(
            asg_id, date_start="2026-03-03", date_end="2026-03-05",
        )
        asg = self.env["project.task.resource.assignment"].browse(asg_id)
        self.assertEqual(asg.date_start.day, 3)
        self.assertEqual(asg.date_end.day, 5)

        # The compact row summary feeds the WBS badge.
        row = next(
            item for item in project.get_planner_data()["tasks"]
            if item["id"] == task.id
        )
        self.assertEqual(row["resources"]["human"], 1)
        self.assertEqual(row["resources"]["open"], 1)

        task.planner_unassign_resource(req["assignments"][0]["id"])
        req = task.get_planner_resources()["requirements"][0]
        self.assertEqual(req["assigned_quantity"], 0)
        self.assertEqual(req["status"], "waiting")

    def test_get_planner_detail_includes_baseline_and_impact(self):
        project = self.env["project.project"].create({"name": "Baseline detail"})
        task = self._make_task(
            project, "Baseline task",
            date_assign="2026-03-01 09:00:00", date_deadline="2026-03-11 18:00:00",
            allocated_hours=16.0,
        )
        project.action_create_critical_path_baseline()
        # Current plan moves later; baseline snapshot must stay frozen.
        task.write({"date_deadline": "2026-03-14 18:00:00"})

        detail = task.get_planner_detail()
        baseline = detail["baseline"]
        impact = detail["impact"]

        self.assertTrue(baseline["has_line"])
        self.assertEqual(baseline["name"], "v1.0")
        self.assertEqual(baseline["date_start"], "2026-03-01")
        self.assertEqual(baseline["date_stop"], "2026-03-11")
        self.assertEqual(baseline["duration_days"], 11)
        self.assertEqual(baseline["allocated_hours"], 16.0)
        # Current values still come from the live task
        self.assertEqual(detail["task"]["date_stop"], "2026-03-14")
        self.assertIn("delay_project_impact", impact)
        self.assertIn("delay_duration_variance", impact)
        self.assertIn("delay_impact_status", impact)

        # The planner list feeds the Gantt baseline ghost bar
        row = next(r for r in project.get_planner_data()["tasks"] if r["id"] == task.id)
        self.assertEqual(row["baseline_name"], "v1.0")
        self.assertEqual(row["baseline_start"], "2026-03-01")
        self.assertEqual(row["baseline_stop"], "2026-03-11")

    def test_get_planner_detail_without_baseline(self):
        project = self.env["project.project"].create({"name": "No baseline"})
        task = self._make_task(project, "Unbaselined task")

        baseline = task.get_planner_detail()["baseline"]

        self.assertFalse(baseline["name"])
        self.assertFalse(baseline["has_line"])
        self.assertFalse(baseline["date_start"])
        self.assertFalse(baseline["duration_days"])
