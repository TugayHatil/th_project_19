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
            "task_id": task.id, "role_id": role.id, "quantity": 2, "planned_hours": 80,
        })
        first = self.env["hr.employee"].create({"name": "First welder"})
        second = self.env["hr.employee"].create({"name": "Second welder"})
        Assignment = self.env["project.task.resource.assignment"]

        Assignment.create({"requirement_id": requirement.id, "employee_id": first.id, "planned_hours": 40})
        self.assertEqual((requirement.assigned_quantity, requirement.assigned_hours), (1, 40))
        self.assertEqual(requirement.assignment_status, "partial")
        Assignment.create({"requirement_id": requirement.id, "employee_id": second.id, "planned_hours": 40})
        self.assertEqual((requirement.assigned_quantity, requirement.assigned_hours), (2, 80))
        self.assertEqual(requirement.assignment_status, "assigned")
