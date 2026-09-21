# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestResourcePlanning(TransactionCase):
    """Resource requirements, assignments and the planner picker."""

    def _make_task(self, project, name, parent=None, **values):
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
            "parent_id": parent.id if parent else False,
            **values,
        })


    def test_task_resource_requirements_build_project_resource_plan(self):
        project = self.env["project.project"].create({"name": "Resource plan test"})
        task_1 = self.env["project.task"].create({"name": "Task 1", "project_id": project.id})
        task_2 = self.env["project.task"].create({"name": "Task 2", "project_id": project.id})
        welder = self.env["project.resource.role"].create({"name": "Welder", "category": "human"})
        crane = self.env["project.resource.role"].create({"name": "Crane", "category": "equipment"})

        self.env["project.task.resource.requirement"].create([
            {"task_id": task_1.id, "role_id": welder.id, "quantity": 2, "planned_hours": 80},
            {"task_id": task_2.id, "role_id": welder.id, "quantity": 1, "planned_hours": 40},
            {"task_id": task_2.id, "role_id": crane.id, "quantity": 1, "planned_hours": 24},
        ])

        welder_summary = project.resource_plan_summary_ids.filtered(
            lambda summary: summary.role_id == welder
        )
        crane_summary = project.resource_plan_summary_ids.filtered(
            lambda summary: summary.role_id == crane
        )
        self.assertEqual((welder_summary.total_quantity, welder_summary.total_planned_hours), (3, 120))
        self.assertEqual((crane_summary.total_quantity, crane_summary.total_planned_hours), (1, 24))
        self.assertEqual(project.resource_requirement_ids.mapped("task_id"), task_1 | task_2)

    def test_resource_assignment_tracks_coverage_and_validates_limits(self):
        project = self.env["project.project"].create({"name": "Assignment test"})
        task = self.env["project.task"].create({"name": "Task", "project_id": project.id})
        role = self.env["project.resource.role"].create({"name": "Welder", "category": "human"})
        requirement = self.env["project.task.resource.requirement"].create({
            "task_id": task.id, "role_id": role.id, "quantity": 2, "planned_hours": 16,
            "date_start": "2026-01-14 08:00:00", "date_end": "2026-01-15 17:00:00",
        })
        first = self.env["hr.employee"].create({
            "name": "First welder", "resource_role_ids": [(4, role.id)],
        })
        second = self.env["hr.employee"].create({
            "name": "Second welder", "resource_role_ids": [(4, role.id)],
        })
        Assignment = self.env["project.task.resource.assignment"]

        Assignment.create({
            "requirement_id": requirement.id, "employee_id": first.id,
            "date_start": "2026-01-14 08:00:00", "date_end": "2026-01-14 17:00:00",
        })
        self.assertEqual(requirement.assigned_quantity, 1)
        self.assertEqual(requirement.assignment_status, "partial")
        Assignment.create({
            "requirement_id": requirement.id, "employee_id": second.id,
            "date_start": "2026-01-15 08:00:00", "date_end": "2026-01-15 17:00:00",
        })
        self.assertEqual(requirement.assigned_quantity, 2)
        self.assertEqual(requirement.assignment_status, "assigned")

    def test_resource_planner_filters_assignments_by_requirement_category(self):
        project = self.env["project.project"].create({"name": "Planner test"})
        task = self.env["project.task"].create({"name": "Task", "project_id": project.id})
        role = self.env["project.resource.role"].create({"name": "Foreman", "category": "human"})
        other_role = self.env["project.resource.role"].create({"name": "Welder", "category": "human"})
        unassigned_employee = self.env["hr.employee"].create({"name": "Unassigned foreman"})
        qualified_employee = self.env["hr.employee"].create({
            "name": "Qualified foreman", "resource_role_ids": [(4, role.id)],
        })
        unqualified_employee = self.env["hr.employee"].create({
            "name": "Unqualified welder", "resource_role_ids": [(4, other_role.id)],
        })
        requirement = self.env["project.task.resource.requirement"].create({
            "task_id": task.id, "role_id": role.id, "quantity": 1, "planned_hours": 8,
            "date_start": "2026-09-14 08:00:00", "date_end": "2026-09-19 18:00:00",
        })

        action = requirement.action_open_resource_planner()
        self.assertEqual(action["view_mode"], "form")
        planner = self.env["project.resource.planner"].browse(action["res_id"])
        self.assertEqual(planner.requirement_id, requirement)
        self.assertTrue(planner.line_ids)
        qualified_line = planner.line_ids.filtered(lambda line: line.employee_id == qualified_employee)
        self.assertEqual(qualified_line.availability_status, "fully_available")
        self.assertNotIn(unassigned_employee, planner.line_ids.mapped("employee_id"))
        self.assertNotIn(unqualified_employee, planner.line_ids.mapped("employee_id"))
        self.assertIn("Task - Foreman", requirement.display_name)
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



class TestResourceRatePlanning(TransactionCase):
    """Per-role rate templates → planned cost snapshot (BRD-20 rev3).

    A rate template carries one currency + hourly rate and may be bound to
    a role. The project selects the templates it plans with; a requirement
    resolves the rate of the template matching its role (role-less
    templates act as fallback) and stores it as a snapshot.
    """

    def _template(self, rate, role=None, name="EUR – Standard"):
        return self.env["project.resource.rate.template"].create({
            "name": name,
            "currency_id": self.env.company.currency_id.id,
            "hourly_rate": rate,
            "role_id": role.id if role else False,
        })

    def _project(self, name, templates):
        return self.env["project.project"].create({
            "name": name,
            "resource_rate_template_ids": [(6, 0, templates.ids)],
        })

    def _requirement(self, project, role, hours, qty=1.0):
        task = self.env["project.task"].create({
            "name": "Resourced task", "project_id": project.id,
        })
        return self.env["project.task.resource.requirement"].create({
            "task_id": task.id,
            "role_id": role.id,
            "planned_hours": hours,
            "quantity": qty,
        })

    def _role(self, name, priority):
        return self.env["project.resource.role"].create(
            {"name": name, "category": "human", "priority": str(priority)})

    def test_planned_cost_uses_role_template_rate(self):
        foreman = self._role("Foreman", 4)
        project = self._project("Costed", self._template(50.0, role=foreman))
        req = self._requirement(project, foreman, hours=16.0)

        self.assertEqual(req.hourly_rate, 50.0)
        self.assertEqual(req.planned_cost, 800.0)

    def test_each_role_uses_its_own_template_rate(self):
        foreman = self._role("Foreman", 4)
        operator = self._role("Crane Op.", 3)
        project = self._project(
            "Per role",
            self._template(50.0, role=foreman) + self._template(40.0, role=operator),
        )
        req_a = self._requirement(project, foreman, hours=16.0)
        req_b = self._requirement(project, operator, hours=8.0)

        self.assertEqual(req_a.planned_cost, 800.0)
        self.assertEqual(req_b.planned_cost, 320.0)

    def test_roleless_template_is_fallback(self):
        foreman = self._role("Foreman", 4)
        welder = self._role("Welder", 3)
        project = self._project("Fallback", self._template(50.0))
        req = self._requirement(project, welder, hours=8.0)

        self.assertEqual(req.hourly_rate, 50.0)
        self.assertEqual(req.planned_cost, 400.0)

    def test_requirement_level_comes_from_role(self):
        foreman = self._role("Foreman", 4)
        project = self._project("Level", self._template(50.0, role=foreman))
        req = self._requirement(project, foreman, hours=8.0)

        self.assertEqual(req.level, "4")

    def test_quantity_multiplies_planned_cost(self):
        worker = self._role("Worker", 2)
        project = self._project("Qty", self._template(50.0, role=worker))
        req = self._requirement(project, worker, hours=16.0, qty=2.0)

        self.assertEqual(req.planned_cost, 1600.0)

    def test_no_template_means_no_planned_cost(self):
        welder = self._role("Welder", 3)
        project = self.env["project.project"].create({"name": "No template"})
        req = self._requirement(project, welder, hours=8.0)

        self.assertEqual(req.hourly_rate, 0.0)
        self.assertEqual(req.planned_cost, 0.0)

    def test_uncovered_role_means_no_planned_cost(self):
        foreman = self._role("Foreman", 4)
        welder = self._role("Welder", 3)
        project = self._project("Covered", self._template(50.0, role=foreman))
        req = self._requirement(project, welder, hours=8.0)

        self.assertEqual(req.hourly_rate, 0.0)
        self.assertEqual(req.planned_cost, 0.0)

    def test_template_edit_does_not_reprice_existing_requirements(self):
        foreman = self._role("Foreman", 4)
        template = self._template(50.0, role=foreman)
        project = self._project("Snapshot", template)
        req = self._requirement(project, foreman, hours=16.0)

        template.hourly_rate = 55.0

        self.assertEqual(req.hourly_rate, 50.0)
        self.assertEqual(req.planned_cost, 800.0)

    def test_project_snapshots_currency_on_template_selection(self):
        foreman = self._role("Foreman", 4)
        template = self._template(50.0, role=foreman)
        project = self._project("Snap", template)

        self.assertEqual(project.resource_currency_id, template.currency_id)

    def test_assignment_does_not_change_planned_cost(self):
        foreman = self._role("Foreman", 4)
        project = self._project("Assign", self._template(50.0, role=foreman))
        req = self._requirement(project, foreman, hours=16.0)
        employee = self.env["hr.employee"].create({
            "name": "Tugay", "resource_role_ids": [(4, foreman.id)],
        })
        self.env["project.task.resource.assignment"].create({
            "requirement_id": req.id,
            "employee_id": employee.id,
            "date_start": "2026-03-02 09:00:00",
            "date_end": "2026-03-02 18:00:00",
        })

        self.assertEqual(req.level, "4")
        self.assertEqual(req.hourly_rate, 50.0)
        self.assertEqual(req.planned_cost, 800.0)

    def test_project_planned_resource_cost_sums_requirements(self):
        foreman = self._role("Foreman", 4)
        operator = self._role("Crane Op.", 3)
        worker = self._role("Worker", 2)
        project = self._project(
            "Totals",
            self._template(50.0, role=foreman)
            + self._template(50.0, role=operator)
            + self._template(50.0, role=worker),
        )
        self._requirement(project, foreman, hours=16.0)
        self._requirement(project, operator, hours=8.0)
        self._requirement(project, worker, hours=24.0)

        self.assertEqual(project.planned_resource_cost, 2400.0)


class TestBaselineCostHistory(TransactionCase):
    """Baseline snapshots freeze planned resource cost; history compares
    consecutive baselines on cost as well as duration (BRD-21)."""

    def _setup(self, rate=50.0):
        role = self.env["project.resource.role"].create(
            {"name": "Foreman", "category": "human", "priority": "4"})
        template = self.env["project.resource.rate.template"].create({
            "name": "EUR – Standard",
            "currency_id": self.env.company.currency_id.id,
            "hourly_rate": rate,
            "role_id": role.id,
        })
        project = self.env["project.project"].create({
            "name": "Costed baseline",
            "resource_rate_template_ids": [(6, 0, template.ids)],
        })
        task = self.env["project.task"].create({
            "name": "Assembly", "project_id": project.id, "allocated_hours": 16.0,
        })
        req = self.env["project.task.resource.requirement"].create({
            "task_id": task.id, "role_id": role.id, "planned_hours": 100.0,
        })
        return project, task, req, template

    def _baseline(self, project):
        project.action_create_critical_path_baseline()
        return self.env["project.critical.path.baseline"].search(
            [("project_id", "=", project.id)], order="revision_number desc", limit=1,
        )

    def test_baseline_freezes_planned_cost_and_currency(self):
        project, task, req, template = self._setup()
        baseline = self._baseline(project)

        self.assertEqual(baseline.planned_resource_hours, 100.0)
        self.assertEqual(baseline.planned_resource_cost, 5000.0)
        self.assertEqual(baseline.currency_id, template.currency_id)
        line = baseline.line_ids.filtered(lambda l: l.task_id == task)
        self.assertEqual(line.planned_hours, 100.0)
        self.assertEqual(line.planned_cost, 5000.0)

        # Later template/rate edits never move the frozen baseline
        template.hourly_rate = 99.0
        req.hourly_rate = 99.0
        self.assertEqual(baseline.planned_resource_cost, 5000.0)
        self.assertEqual(line.planned_cost, 5000.0)

    def test_cost_variance_between_baselines(self):
        project, task, req, template = self._setup()
        first = self._baseline(project)

        req.planned_hours = 120.0
        second = self._baseline(project)

        self.assertEqual(second.planned_resource_cost, 6000.0)
        self.assertEqual(second.previous_baseline_id, first)
        self.assertEqual(second.history_planned_cost_variance, 1000.0)

    def test_rate_change_alone_produces_cost_delta(self):
        project, task, req, template = self._setup()
        self._baseline(project)

        req.hourly_rate = 60.0  # hours unchanged: 100h × 60 = 6000
        second = self._baseline(project)

        self.assertEqual(second.planned_resource_cost, 6000.0)
        self.assertEqual(second.history_planned_cost_variance, 1000.0)
        self.assertEqual(second.history_project_duration_variance, 0.0)

    def test_cost_decrease_variance_is_negative(self):
        project, task, req, template = self._setup()
        self._baseline(project)
        req.hourly_rate = 60.0
        second = self._baseline(project)

        req.hourly_rate = 50.0
        third = self._baseline(project)

        self.assertEqual(third.planned_resource_cost, 5000.0)
        self.assertEqual(third.history_planned_cost_variance, -1000.0)

    def test_history_payload_includes_cost_fields(self):
        project, task, req, template = self._setup()
        self._baseline(project)
        req.hourly_rate = 60.0
        self._baseline(project)

        history = project.get_planner_baseline_history()
        newest = history[0]
        self.assertEqual(newest["planned_cost"], 6000.0)
        self.assertEqual(newest["cost_variance"], 1000.0)
        self.assertEqual(newest["currency_symbol"], template.currency_id.symbol)

    def test_summary_payload_includes_task_cost_deltas(self):
        project, task, req, template = self._setup()
        self._baseline(project)
        req.hourly_rate = 60.0
        second = self._baseline(project)

        summary = project.get_planner_baseline_summary(second.id)
        self.assertEqual(summary["planned_cost"], 6000.0)
        self.assertEqual(summary["previous_cost"], 5000.0)
        self.assertEqual(summary["cost_variance"], 1000.0)
        change = next(c for c in summary["changes"] if c["task_id"] == task.id)
        # Rate-only change: hours delta is 0 but cost delta must surface
        self.assertEqual(change["delta_hours"], 0.0)
        self.assertEqual(change["old_cost"], 5000.0)
        self.assertEqual(change["new_cost"], 6000.0)
        self.assertEqual(change["delta_cost"], 1000.0)


