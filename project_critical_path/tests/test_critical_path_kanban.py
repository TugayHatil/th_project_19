# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestCriticalPathKanbanHighlight(TransactionCase):
    """BRD-10: Critical Path Highlight in Project Kanban.

    Verifies that:
    - is_critical is set correctly after critical path calculation
    - the kanban view inheritance is loaded and references is_critical
    - non-critical tasks keep is_critical=False
    """

    def test_is_critical_flag_is_set_after_calculation(self):
        project = self.env["project.project"].create({"name": "Kanban highlight test"})
        task_1 = self.env["project.task"].create({
            "name": "Critical Task 1", "project_id": project.id, "allocated_hours": 3,
        })
        task_2 = self.env["project.task"].create({
            "name": "Critical Task 2", "project_id": project.id, "allocated_hours": 6,
            "depend_on_ids": [(4, task_1.id)],
        })
        task_3 = self.env["project.task"].create({
            "name": "Non-critical parallel task", "project_id": project.id, "allocated_hours": 1,
        })

        project.action_calculate_critical_paths()

        self.assertTrue(task_1.is_critical, "First task on the critical path should be flagged")
        self.assertTrue(task_2.is_critical, "Second task on the critical path should be flagged")
        self.assertFalse(task_3.is_critical, "Parallel task with slack should not be flagged")

    def test_kanban_view_inheritance_is_loaded(self):
        """The inherited kanban view must exist and expose is_critical."""
        View = self.env["ir.ui.view"]
        kanban_view = View.search([
            ("inherit_id", "=", self.env.ref("project.view_task_kanban").id),
            ("model", "=", "project.task"),
        ], limit=1)
        self.assertTrue(kanban_view, "Inherited project.task kanban view should be installed")
        arch = kanban_view.arch
        self.assertIn("is_critical", arch, "Kanban view must expose is_critical field")
        self.assertIn(
            "o_critical_path_kanban",
            arch,
            "Kanban view must add the critical highlight CSS class",
        )
        self.assertIn(
            "Critical Path",
            arch,
            "Kanban view must include the Critical Path tooltip",
        )

    def test_non_critical_tasks_are_not_affected_by_view(self):
        """The kanban view should only add classes when is_critical is True."""
        project = self.env["project.project"].create({"name": "Non-critical test"})
        task = self.env["project.task"].create({
            "name": "Lone task", "project_id": project.id, "allocated_hours": 2,
        })
        project.action_calculate_critical_paths()
        self.assertFalse(task.is_critical, "Lone task should not be critical")
