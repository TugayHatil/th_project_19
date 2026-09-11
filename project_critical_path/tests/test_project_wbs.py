# -*- coding: utf-8 -*-

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestProjectWBS(TransactionCase):

    def setUp(self):
        super().setUp()
        self.project = self.env["project.project"].create({"name": "WBS Test Project"})
        self.manager = self.env["res.users"].create({
            "name": "WBS Project Manager",
            "login": "wbs_manager",
            "groups_id": [(6, 0, [
                self.env.ref("project.group_project_manager").id,
                self.env.ref("base.group_user").id,
            ])],
        })
        self.regular_user = self.env["res.users"].create({
            "name": "WBS Regular User",
            "login": "wbs_user",
            "groups_id": [(6, 0, [
                self.env.ref("project.group_project_user").id,
                self.env.ref("base.group_user").id,
            ])],
        })

    def test_ac01_and_cases_1_2_3_automatic_wbs_numbering(self):
        """AC-01: Every task automatically receives a valid WBS code."""
        # Case 1: First root task
        task_1 = self.env["project.task"].create({
            "name": "Engineering",
            "project_id": self.project.id,
            "sequence": 10,
        })
        self.assertEqual(task_1.wbs_code, "1")
        self.assertEqual(task_1.wbs_level, 1)
        self.assertFalse(task_1.is_work_package)

        # Case 2: Second root task
        task_2 = self.env["project.task"].create({
            "name": "Procurement",
            "project_id": self.project.id,
            "sequence": 20,
        })
        self.assertEqual(task_2.wbs_code, "2")
        self.assertEqual(task_2.wbs_level, 1)
        self.assertFalse(task_2.is_work_package)

        # Case 3: Add child task
        child_2_1 = self.env["project.task"].create({
            "name": "Layout Drawing",
            "project_id": self.project.id,
            "parent_id": task_2.id,
            "sequence": 10,
        })
        self.assertEqual(child_2_1.wbs_code, "2.1")
        self.assertEqual(child_2_1.wbs_level, 2)
        self.assertTrue(task_2.is_work_package)

        child_2_2 = self.env["project.task"].create({
            "name": "Detail Drawing",
            "project_id": self.project.id,
            "parent_id": task_2.id,
            "sequence": 20,
        })
        self.assertEqual(child_2_2.wbs_code, "2.2")

        grandchild_2_2_1 = self.env["project.task"].create({
            "name": "Component Specs",
            "project_id": self.project.id,
            "parent_id": child_2_2.id,
            "sequence": 10,
        })
        self.assertEqual(grandchild_2_2_1.wbs_code, "2.2.1")
        self.assertEqual(grandchild_2_2_1.wbs_level, 3)
        self.assertTrue(child_2_2.is_work_package)

    def test_ac02_case4_moving_subtree_renumbers_hierarchy(self):
        """AC-02 & Case 4: Moving subtree updates moved task and descendants."""
        root_1 = self.env["project.task"].create({"name": "Root 1", "project_id": self.project.id, "sequence": 10})
        root_2 = self.env["project.task"].create({"name": "Root 2", "project_id": self.project.id, "sequence": 20})
        c1 = self.env["project.task"].create({"name": "Child 1.1", "project_id": self.project.id, "parent_id": root_1.id, "sequence": 10})
        c2 = self.env["project.task"].create({"name": "Child 1.2", "project_id": self.project.id, "parent_id": root_1.id, "sequence": 20})
        gc = self.env["project.task"].create({"name": "Grandchild 1.2.1", "project_id": self.project.id, "parent_id": c2.id, "sequence": 10})

        self.assertEqual(c2.wbs_code, "1.2")
        self.assertEqual(gc.wbs_code, "1.2.1")

        # Move c2 under root_2 using manager user
        c2.with_user(self.manager).write({"parent_id": root_2.id})

        self.assertEqual(c2.wbs_code, "2.1")
        self.assertEqual(gc.wbs_code, "2.1.1")
        self.assertEqual(c1.wbs_code, "1.1")

    def test_ac04_case5_delete_middle_task_closes_gaps(self):
        """AC-04 & Case 5: Delete middle task, remaining siblings close gaps."""
        t1 = self.env["project.task"].create({"name": "Task 1", "project_id": self.project.id, "sequence": 10})
        t2 = self.env["project.task"].create({"name": "Task 2", "project_id": self.project.id, "sequence": 20})
        t3 = self.env["project.task"].create({"name": "Task 3", "project_id": self.project.id, "sequence": 30})

        self.assertEqual(t1.wbs_code, "1")
        self.assertEqual(t2.wbs_code, "2")
        self.assertEqual(t3.wbs_code, "3")

        t2.unlink()
        self.project._recalculate_wbs()

        self.assertEqual(t1.wbs_code, "1")
        self.assertEqual(t3.wbs_code, "2")

    def test_ac05_ac06_rollup_calculations(self):
        """AC-05 & AC-06: Roll-up hours equal sum of descendants and weighted progress."""
        root = self.env["project.task"].create({
            "name": "Root Task",
            "project_id": self.project.id,
            "allocated_hours": 0.0,
        })
        c1 = self.env["project.task"].create({
            "name": "Task A",
            "project_id": self.project.id,
            "parent_id": root.id,
            "allocated_hours": 10.0,
            "effective_hours": 10.0,
            "progress": 100.0,
        })
        c2 = self.env["project.task"].create({
            "name": "Task B",
            "project_id": self.project.id,
            "parent_id": root.id,
            "allocated_hours": 20.0,
            "effective_hours": 10.0,
            "progress": 50.0,
        })

        self.project._recalculate_wbs_rollups()

        self.assertEqual(c1.planned_hours_rollup, 10.0)
        self.assertEqual(c1.effective_hours_rollup, 10.0)
        self.assertEqual(c1.progress_rollup, 100.0)

        self.assertEqual(c2.planned_hours_rollup, 20.0)
        self.assertEqual(c2.effective_hours_rollup, 10.0)
        self.assertEqual(c2.progress_rollup, 50.0)

        # Root rollups: planned = 30, effective = 20, weighted progress = (10*100 + 20*50)/30 = 66.67
        self.assertEqual(root.planned_hours_rollup, 30.0)
        self.assertEqual(root.effective_hours_rollup, 20.0)
        self.assertAlmostEqual(root.progress_rollup, 66.67, places=2)

    def test_case6_ten_level_deep_hierarchy(self):
        """Case 6: 10-level hierarchy renumbers correctly."""
        parent = False
        tasks = []
        for level in range(1, 11):
            task = self.env["project.task"].create({
                "name": f"Level {level} Task",
                "project_id": self.project.id,
                "parent_id": parent.id if parent else False,
                "sequence": 10,
            })
            tasks.append(task)
            parent = task

        expected_code = "1"
        for idx, task in enumerate(tasks, start=1):
            self.assertEqual(task.wbs_level, idx)
            self.assertEqual(task.wbs_code, expected_code)
            expected_code += ".1"

    def test_security_only_manager_can_modify_hierarchy(self):
        """Security: Non-manager users cannot change task hierarchy."""
        root = self.env["project.task"].create({"name": "Root", "project_id": self.project.id})
        other_root = self.env["project.task"].create({"name": "Other Root", "project_id": self.project.id})
        child = self.env["project.task"].create({"name": "Child", "project_id": self.project.id, "parent_id": root.id})

        with self.assertRaises(UserError):
            child.with_user(self.regular_user).write({"parent_id": other_root.id})

        # Manager user succeeds
        child.with_user(self.manager).write({"parent_id": other_root.id})
        self.assertEqual(child.parent_id, other_root)
