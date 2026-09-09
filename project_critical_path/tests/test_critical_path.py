# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestCriticalPath(TransactionCase):
    def test_longest_dependency_chain_is_saved(self):
        project = self.env["project.project"].create({"name": "Critical path test"})
        task_1 = self.env["project.task"].create({"name": "Task 1", "project_id": project.id, "allocated_hours": 3})
        task_2 = self.env["project.task"].create({"name": "Task 2", "project_id": project.id, "allocated_hours": 6, "depend_on_ids": [(4, task_1.id)]})
        task_3 = self.env["project.task"].create({"name": "Task 3", "project_id": project.id, "allocated_hours": 5, "depend_on_ids": [(4, task_2.id)]})
        task_4 = self.env["project.task"].create({"name": "Task 4", "project_id": project.id, "allocated_hours": 15, "depend_on_ids": [(4, task_2.id)]})
        self.env["project.task"].create({"name": "Task 5", "project_id": project.id, "allocated_hours": 3, "depend_on_ids": [(4, task_3.id), (4, task_4.id)]})

        project.action_calculate_critical_paths()

        self.assertEqual(project.critical_path_count, 1)
        self.assertEqual(project.critical_path_duration, 27)
        self.assertEqual(project.critical_path_ids.task_path, "Task 1 → Task 2 → Task 4 → Task 5")
        self.assertEqual(task_3.critical_early_start, 9)
        self.assertEqual(task_3.critical_early_finish, 14)
        self.assertEqual(task_3.critical_late_start, 19)
        self.assertEqual(task_3.critical_late_finish, 24)
        self.assertEqual(task_3.critical_slack, 10)
        self.assertEqual(task_4.critical_slack, 0)

    def test_equal_maximum_paths_are_all_saved(self):
        project = self.env["project.project"].create({"name": "Parallel critical paths"})
        first = self.env["project.task"].create({"name": "First", "project_id": project.id, "allocated_hours": 4})
        second = self.env["project.task"].create({"name": "Second", "project_id": project.id, "allocated_hours": 4})
        self.env["project.task"].create({"name": "Finish", "project_id": project.id, "allocated_hours": 2, "depend_on_ids": [(4, first.id), (4, second.id)]})

        project.action_calculate_critical_paths()

        self.assertEqual(project.critical_path_count, 2)
        self.assertEqual(project.critical_path_duration, 6)
