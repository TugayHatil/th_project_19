# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestCriticalPath(TransactionCase):
    def test_longest_dependency_chain_is_saved(self):
        project = self.env["project.project"].create({"name": "Critical path test"})
        task_1 = self.env["project.task"].create({"name": "Task 1", "project_id": project.id, "allocated_hours": 3})
        task_2 = self.env["project.task"].create({"name": "Task 2", "project_id": project.id, "allocated_hours": 6, "depend_on_ids": [(4, task_1.id)]})
        task_3 = self.env["project.task"].create({"name": "Task 3", "project_id": project.id, "allocated_hours": 5, "depend_on_ids": [(4, task_2.id)]})
        task_4 = self.env["project.task"].create({"name": "Task 4", "project_id": project.id, "allocated_hours": 15, "depend_on_ids": [(4, task_2.id)]})
        task_5 = self.env["project.task"].create({"name": "Task 5", "project_id": project.id, "allocated_hours": 3, "depend_on_ids": [(4, task_3.id), (4, task_4.id)]})

        project.action_calculate_critical_paths()

        self.assertEqual(project.critical_path_count, 1)
        self.assertEqual(project.critical_path_duration, 27)
        self.assertEqual(project.critical_path_ids.task_path, "Task 1 → Task 2 → Task 4 → Task 5")
        self.assertEqual((task_1.critical_early_start, task_1.critical_early_finish), (0, 3))
        self.assertEqual((task_2.critical_early_start, task_2.critical_early_finish), (3, 9))
        self.assertEqual((task_3.critical_early_start, task_3.critical_early_finish), (9, 14))
        self.assertEqual((task_4.critical_early_start, task_4.critical_early_finish), (9, 24))
        self.assertEqual((task_5.critical_early_start, task_5.critical_early_finish), (24, 27))
        self.assertEqual((task_3.critical_late_start, task_3.critical_late_finish), (19, 24))
        self.assertEqual(task_3.critical_slack, 10)
        self.assertFalse(task_3.is_critical)
        self.assertTrue(task_1.is_critical)
        self.assertTrue(task_2.is_critical)
        self.assertTrue(task_4.is_critical)
        self.assertTrue(task_5.is_critical)

        project.action_create_critical_path_baseline()
        task_3.allocated_hours = 8
        self.assertEqual(task_3.delay_baseline_duration, 5)
        self.assertEqual(task_3.delay_duration_variance, 3)
        self.assertEqual(task_3.delay_project_impact, 0)
        self.assertEqual(task_3.delay_impact_status, "within_slack")
        self.assertEqual(project.delay_total, 0)

        task_4.allocated_hours = 18
        self.assertEqual(project.critical_path_duration, 30)
        self.assertEqual(project.delay_total, 3)
        self.assertEqual(task_4.delay_baseline_duration, 15)
        self.assertEqual(task_4.delay_duration_variance, 3)
        self.assertEqual(task_4.delay_project_impact, 3)
        self.assertEqual(task_4.delay_impact_status, "critical_impact")
        self.assertIn("Task 5", task_4.delay_impact_chain)

        task_3.allocated_hours = 21
        baseline = project.critical_path_baseline_ids
        self.assertTrue(baseline.critical_path_changed)
        self.assertEqual(project.critical_path_duration, 33)
        self.assertEqual(
            baseline.critical_path_change_line_ids.filtered(
                lambda change: change.task_id == task_3
            ).change_type,
            "added",
        )
        self.assertEqual(
            baseline.critical_path_change_line_ids.filtered(
                lambda change: change.task_id == task_4
            ).change_type,
            "removed",
        )
        project.action_create_critical_path_baseline()
        history_baseline = project.critical_path_baseline_ids[0]
        self.assertEqual(history_baseline.name, "v1.1")
        self.assertEqual(history_baseline.previous_baseline_id.name, "v1.0")
        self.assertEqual(history_baseline.history_project_duration_variance, 6)
        self.assertEqual(history_baseline.history_critical_path_duration_variance, 6)
        self.assertEqual(history_baseline.history_critical_path_changed, "yes")
        self.assertIn("Task 3", history_baseline.history_added_task_names)
        self.assertIn("Task 4", history_baseline.history_removed_task_names)

    def test_equal_maximum_paths_are_all_saved(self):
        project = self.env["project.project"].create({"name": "Parallel critical paths"})
        first = self.env["project.task"].create({"name": "First", "project_id": project.id, "allocated_hours": 4})
        second = self.env["project.task"].create({"name": "Second", "project_id": project.id, "allocated_hours": 4})
        self.env["project.task"].create({"name": "Finish", "project_id": project.id, "allocated_hours": 2, "depend_on_ids": [(4, first.id), (4, second.id)]})

        project.action_calculate_critical_paths()

        self.assertEqual(project.critical_path_count, 2)
        self.assertEqual(project.critical_path_duration, 6)

    def test_critical_path_runs_from_entry_to_completion(self):
        """BRD-25 Test 3/4: implicit virtual start/finish nodes — the stored
        path must begin at a real entry task and end at the latest
        completion, with every consecutive pair linked by a dependency."""
        project = self.env["project.project"].create({"name": "End-to-end"})
        task_a = self.env["project.task"].create({"name": "A", "project_id": project.id, "allocated_hours": 2})
        task_b = self.env["project.task"].create({"name": "B", "project_id": project.id, "allocated_hours": 3})
        task_c = self.env["project.task"].create({"name": "C", "project_id": project.id, "allocated_hours": 4, "depend_on_ids": [(4, task_a.id)]})
        task_d = self.env["project.task"].create({"name": "D", "project_id": project.id, "allocated_hours": 1, "depend_on_ids": [(4, task_b.id)]})
        task_e = self.env["project.task"].create({"name": "E", "project_id": project.id, "allocated_hours": 5, "depend_on_ids": [(4, task_c.id), (4, task_d.id)]})
        task_f = self.env["project.task"].create({"name": "F", "project_id": project.id, "allocated_hours": 1, "depend_on_ids": [(4, task_e.id)]})

        project.action_calculate_critical_paths()

        # Longest chain: A(2) → C(4) → E(5) → F(1) = 12 beats B→D→E→F = 10.
        self.assertEqual(project.critical_path_duration, 12)
        name_by_id = {task.name: task for task in (task_a, task_b, task_c, task_d, task_e, task_f)}
        for path in project.critical_path_ids:
            names = path.task_path.split(" → ")
            self.assertEqual(names[0], "A")
            self.assertEqual(names[-1], "F")
            for previous, following in zip(names, names[1:]):
                self.assertIn(
                    name_by_id[previous],
                    name_by_id[following].depend_on_ids,
                    msg="Critical path contains a non-dependency step %s → %s" % (previous, following),
                )
        self.assertFalse(task_b.is_critical)
        self.assertFalse(task_d.is_critical)
        self.assertTrue(task_b.critical_slack > 0)

    def test_wbs_parents_stay_off_the_critical_path(self):
        """BRD-25 Test 6: a WBS work package is a container — even with a
        large duration it must not become the critical path by itself."""
        project = self.env["project.project"].create({"name": "WBS test"})
        parent = self.env["project.task"].create({"name": "Phase", "project_id": project.id, "allocated_hours": 100})
        task_a = self.env["project.task"].create({"name": "A", "project_id": project.id, "parent_id": parent.id, "allocated_hours": 4})
        task_b = self.env["project.task"].create({"name": "B", "project_id": project.id, "parent_id": parent.id, "allocated_hours": 6, "depend_on_ids": [(4, task_a.id)]})

        project.action_calculate_critical_paths()

        self.assertEqual(project.critical_path_duration, 10)
        self.assertEqual(project.critical_path_ids.task_path, "A → B")
        self.assertFalse(parent.is_critical)
        self.assertFalse(parent.critical_early_finish)
        self.assertTrue(task_a.is_critical)
        self.assertTrue(task_b.is_critical)
        self.assertNotIn(parent.id, project.critical_path_ids.task_ids.ids)

    def test_dependencies_on_parents_flow_down_to_leaf_children(self):
        """BRD-25: a dependency declared on a WBS container is redirected to
        its leaf descendants, so phase-level links still chain the real work."""
        project = self.env["project.project"].create({"name": "Phase deps"})
        phase_a = self.env["project.task"].create({"name": "Phase A", "project_id": project.id})
        phase_b = self.env["project.task"].create({"name": "Phase B", "project_id": project.id, "depend_on_ids": [(4, phase_a.id)]})
        a1 = self.env["project.task"].create({"name": "A1", "project_id": project.id, "parent_id": phase_a.id, "allocated_hours": 4})
        a2 = self.env["project.task"].create({"name": "A2", "project_id": project.id, "parent_id": phase_a.id, "allocated_hours": 6})
        b1 = self.env["project.task"].create({"name": "B1", "project_id": project.id, "parent_id": phase_b.id, "allocated_hours": 5})

        project.action_calculate_critical_paths()

        # Phase B waits for all of Phase A: B1's predecessors are A1 and A2.
        self.assertEqual(set(b1.depend_on_ids.ids), {phase_a.id})  # untouched record
        self.assertEqual(project.critical_path_duration, 11)
        self.assertEqual(project.critical_path_ids.task_path, "A2 → B1")
        self.assertTrue(a2.is_critical)
        self.assertTrue(b1.is_critical)
        self.assertFalse(a1.is_critical)  # 2h of slack next to A2
        self.assertFalse(phase_a.is_critical)
        self.assertFalse(phase_b.is_critical)

    def test_planner_resize_syncs_duration_and_recalculates_path(self):
        """BRD-25 AC: resizing a bar writes the new span to allocated_hours
        so the critical path immediately recalculates from the current
        planned duration — the GTR parallel-branch scenario."""
        project = self.env["project.project"].create({"name": "GTR scenario"})
        task_a = self.env["project.task"].create({"name": "A", "project_id": project.id, "allocated_hours": 8})
        task_b = self.env["project.task"].create({"name": "B", "project_id": project.id, "allocated_hours": 16, "depend_on_ids": [(4, task_a.id)]})
        task_c = self.env["project.task"].create({"name": "C", "project_id": project.id, "allocated_hours": 8, "depend_on_ids": [(4, task_a.id)]})
        task_d = self.env["project.task"].create({
            "name": "D", "project_id": project.id, "allocated_hours": 8,
            "depend_on_ids": [(4, task_b.id)],
            "date_assign": "2026-03-16 09:00:00", "date_deadline": "2026-03-16 18:00:00",
        })
        task_e = self.env["project.task"].create({"name": "E", "project_id": project.id, "allocated_hours": 8, "depend_on_ids": [(4, task_c.id)]})
        task_f = self.env["project.task"].create({"name": "F", "project_id": project.id, "allocated_hours": 8, "depend_on_ids": [(4, task_d.id), (4, task_e.id)]})

        project.action_calculate_critical_paths()

        # A→B→D→F = 40h beats A→C→E→F = 32h — entry task A starts the path,
        # exit task F ends it, every step is a real dependency.
        self.assertEqual(project.critical_path_duration, 40)
        self.assertEqual(project.critical_path_ids.task_path, "A → B → D → F")
        self.assertFalse(task_c.is_critical)
        self.assertFalse(task_e.is_critical)

        # Planner right-resize: D grows from 1 day to 3 days.
        from odoo.addons.project_critical_path.models.project_planner import (
            _planner_hours_per_day,
        )
        hours_per_day = _planner_hours_per_day(task_d)
        task_d.update_planner_task({
            "date_start": "2026-03-16",
            "date_stop": "2026-03-18",
            "duration_days": 3,
        })

        self.assertAlmostEqual(task_d.allocated_hours, 3 * hours_per_day, places=2)
        # The write hook already recalculated the whole graph: 8+16+24+8 = 56.
        self.assertEqual(project.critical_path_duration, 56)
        self.assertEqual(project.critical_path_ids.task_path, "A → B → D → F")
        self.assertTrue(task_f.is_critical)

    def test_baseline_is_an_immutable_plan_snapshot(self):
        project = self.env["project.project"].create({"name": "Baseline test"})
        first = self.env["project.task"].create({
            "name": "First", "project_id": project.id, "allocated_hours": 3,
        })
        second = self.env["project.task"].create({
            "name": "Second", "project_id": project.id, "allocated_hours": 5,
            "depend_on_ids": [(4, first.id)],
        })

        project.action_create_critical_path_baseline()
        baseline = project.critical_path_baseline_ids
        self.assertEqual(baseline.name, "v1.0")
        self.assertEqual(baseline.project_duration, 8)
        line = baseline.line_ids.filtered(lambda snapshot: snapshot.task_id == second)
        self.assertEqual(line.allocated_hours, 5)
        self.assertEqual(line.early_finish, 8)
        self.assertTrue(line.is_critical)

        second.allocated_hours = 9
        project.action_calculate_critical_paths()
        self.assertEqual(line.allocated_hours, 5)
        self.assertEqual(line.early_finish, 8)
        self.assertEqual(line.current_allocated_hours, 9)
        self.assertEqual(line.allocated_hours_delta, 4)
        self.assertEqual(baseline.current_project_duration, 12)
        self.assertEqual(baseline.project_duration_delta, 4)

        project.action_create_critical_path_baseline()
        self.assertEqual(project.critical_path_baseline_ids[0].name, "v1.1")
        self.assertEqual(project.critical_path_baseline_ids[1].name, "v1.0")
        self.assertFalse(project.critical_path_baseline_ids[1].history_critical_path_changed)
        self.assertEqual(project.critical_path_baseline_ids[0].history_project_duration_variance, 4)
        self.assertEqual(project.critical_path_baseline_ids[0].history_critical_path_changed, "no")

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
