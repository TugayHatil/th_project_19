# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestPlannerWbsActions(TransactionCase):
    """Planner WBS quick-create / indent / outdent / drag-reorder suite.

    Mouse drag = ordering only, Indent/Outdent = hierarchy only. These tests
    pin that split plus WBS code consistency, parent rollup and dependency
    preservation (BRD — WBS Quick Create + Indent/Outdent).
    """

    def _task(self, project, name, start="2026-09-15 09:00:00", stop="2026-09-15 18:00:00",
              parent=None, **values):
        vals = {
            "name": name, "project_id": project.id,
            "date_assign": start, "date_deadline": stop,
        }
        if parent:
            vals["parent_id"] = parent.id
        vals.update(values)
        return self.env["project.task"].create(vals)

    def _wbs(self, task):
        task.invalidate_recordset(["wbs_code", "wbs_level", "wbs_sort_key"])
        return task.wbs_code

    def _ordered_names(self, project, parent=False):
        tasks = self.env["project.task"].search(
            [("project_id", "=", project.id), ("parent_id", "=", parent and parent.id or False)],
            order="sequence, id",
        )
        return tasks.mapped("name")

    # ---- Quick create -----------------------------------------------------

    def test_add_subtask_creates_last_child(self):
        project = self.env["project.project"].create({"name": "WBS add"})
        a = self._task(project, "A")
        existing = self._task(project, "B", parent=a)
        result = a.planner_add_subtask("Child C")
        child = self.env["project.task"].browse(result["id"])
        self.assertEqual(child.parent_id, a)
        self.assertEqual(child.project_id, project)
        self.assertEqual(child.name, "Child C")
        self.assertEqual(self._ordered_names(project, a), ["B", "Child C"])
        self.assertEqual(self._wbs(child), "1.2")

    def test_add_subtask_default_name(self):
        project = self.env["project.project"].create({"name": "WBS add"})
        a = self._task(project, "A")
        result = a.planner_add_subtask("")
        child = self.env["project.task"].browse(result["id"])
        self.assertTrue(child.name)

    # ---- Indent ------------------------------------------------------------

    def test_indent_under_previous_sibling(self):
        project = self.env["project.project"].create({"name": "Indent"})
        a = self._task(project, "A")
        b = self._task(project, "B")
        c = self._task(project, "C")
        self.assertTrue(b.planner_wbs_indent())
        self.assertEqual(b.parent_id, a)
        self.assertEqual(self._wbs(a), "1")
        self.assertEqual(self._wbs(b), "1.1")
        self.assertEqual(self._wbs(c), "2")

    def test_indent_first_sibling_is_noop(self):
        project = self.env["project.project"].create({"name": "Indent first"})
        a = self._task(project, "A")
        b = self._task(project, "B")
        self.assertFalse(a.planner_wbs_indent())
        self.assertFalse(a.parent_id)
        self.assertEqual(self._wbs(a), "1")
        self.assertEqual(self._wbs(b), "2")

    def test_indent_multi_level(self):
        project = self.env["project.project"].create({"name": "Indent deep"})
        a = self._task(project, "A")
        b = self._task(project, "B")
        c = self._task(project, "C")
        b.planner_wbs_indent()
        c.planner_wbs_indent()   # C's previous sibling is now A (root) — wait,
        # B was removed from root siblings, so C indents under A.
        self.assertEqual(c.parent_id, a)
        self.assertEqual(self._wbs(c), "1.2")
        c.planner_wbs_indent()   # under B now (1.1 < 1.2 ordering)
        self.assertEqual(c.parent_id, b)
        self.assertEqual(self._wbs(c), "1.1.1")

    # ---- Outdent -----------------------------------------------------------

    def test_outdent_lands_after_parent(self):
        project = self.env["project.project"].create({"name": "Outdent"})
        a = self._task(project, "A")
        b = self._task(project, "B", parent=a)
        c = self._task(project, "C", parent=a)
        d = self._task(project, "D")
        self.assertTrue(b.planner_wbs_outdent())
        self.assertFalse(b.parent_id)
        # B lands right after its former parent: A, B, D roots.
        self.assertEqual(self._ordered_names(project), ["A", "B", "D"])
        self.assertEqual(self._wbs(b), "2")
        self.assertEqual(self._wbs(c), "1.1")
        self.assertEqual(self._wbs(d), "3")

    def test_outdent_multi_level(self):
        project = self.env["project.project"].create({"name": "Outdent deep"})
        a = self._task(project, "A")
        b = self._task(project, "B", parent=a)
        c = self._task(project, "C", parent=b)
        c.planner_wbs_outdent()
        self.assertEqual(c.parent_id, a)
        self.assertEqual(self._wbs(c), "1.2")
        c.planner_wbs_outdent()
        self.assertFalse(c.parent_id)
        self.assertEqual(self._wbs(c), "2")

    def test_outdent_root_is_noop(self):
        project = self.env["project.project"].create({"name": "Outdent root"})
        a = self._task(project, "A")
        self.assertFalse(a.planner_wbs_outdent())
        self.assertFalse(a.parent_id)
        self.assertEqual(self._wbs(a), "1")

    # ---- Reorder (drag) -----------------------------------------------------

    def test_move_before_reorders_siblings(self):
        project = self.env["project.project"].create({"name": "Reorder"})
        a = self._task(project, "A")
        b = self._task(project, "B")
        c = self._task(project, "C")
        self.assertTrue(c.planner_wbs_move_before(b.id))
        self.assertEqual(self._ordered_names(project), ["A", "C", "B"])
        self.assertEqual(self._wbs(c), "2")
        self.assertEqual(self._wbs(b), "3")

    def test_move_before_never_reparents(self):
        project = self.env["project.project"].create({"name": "Reorder safe"})
        a = self._task(project, "A")
        child = self._task(project, "Child", parent=a)
        other = self._task(project, "Other")
        # A cross-branch drop target is rejected — hierarchy untouched.
        self.assertFalse(child.planner_wbs_move_before(other.id))
        self.assertEqual(child.parent_id, a)
        self.assertTrue(other.planner_wbs_move_before(a.id))
        self.assertEqual(self._ordered_names(project), ["Other", "A"])

    def test_move_before_end(self):
        project = self.env["project.project"].create({"name": "Reorder end"})
        a = self._task(project, "A")
        b = self._task(project, "B")
        self.assertTrue(a.planner_wbs_move_before(False))
        self.assertEqual(self._ordered_names(project), ["B", "A"])

    def test_child_reorder_inside_parent(self):
        project = self.env["project.project"].create({"name": "Child reorder"})
        a = self._task(project, "A")
        b = self._task(project, "B", parent=a)
        c = self._task(project, "C", parent=a)
        d = self._task(project, "D", parent=a)
        d.planner_wbs_move_before(c.id)
        self.assertEqual(self._ordered_names(project, a), ["B", "D", "C"])
        self.assertEqual(self._wbs(d), "1.2")
        self.assertEqual(self._wbs(c), "1.3")
        # Parents never moved.
        self.assertEqual(b.parent_id, a)
        self.assertEqual(d.parent_id, a)
        self.assertEqual(c.parent_id, a)

    # ---- Safety: rollup + dependencies -------------------------------------

    def test_rollup_after_hierarchy_change(self):
        project = self.env["project.project"].create({"name": "Rollup"})
        a = self._task(project, "A")
        b = self._task(project, "B", start="2026-09-10 09:00:00", stop="2026-09-12 18:00:00")
        c = self._task(project, "C", start="2026-09-20 09:00:00", stop="2026-09-22 18:00:00")
        b.planner_wbs_indent()   # under A
        c.planner_wbs_indent()   # under A too (prev sibling at root is A? no —
        # after B indents, root order is A, C → C's prev sibling is A)
        self.assertEqual(c.parent_id, a)
        a.invalidate_recordset(["date_assign", "date_deadline"])
        self.assertEqual(a.date_assign.strftime("%Y-%m-%d %H:%M:%S"), "2026-09-10 09:00:00")
        self.assertEqual(a.date_deadline.strftime("%Y-%m-%d %H:%M:%S"), "2026-09-22 18:00:00")

    def test_dependency_survives_indent(self):
        project = self.env["project.project"].create({"name": "Deps"})
        a = self._task(project, "A")
        b = self._task(project, "B", depend_on_ids=[(4, a.id)])
        c = self._task(project, "C")
        c.planner_wbs_indent()
        self.assertEqual(c.parent_id, b)
        self.assertEqual(b.depend_on_ids, a)

    def test_rapid_mixed_ops_consistency(self):
        project = self.env["project.project"].create({"name": "Rapid"})
        a = self._task(project, "A")
        b = self._task(project, "B")
        c = self._task(project, "C")
        d = self._task(project, "D")
        b.planner_wbs_indent()
        d.planner_wbs_move_before(c.id)
        b.planner_wbs_outdent()
        c.planner_wbs_indent()
        codes = [
            self._wbs(t) for t in self.env["project.task"].search(
                [("project_id", "=", project.id)]
            ).sorted("wbs_sort_key")
        ]
        self.assertEqual(len(codes), len(set(codes)))  # no duplicates
        # Every code parses and levels are consistent.
        for task in self.env["project.task"].search([("project_id", "=", project.id)]):
            self.assertEqual(task.wbs_level, task.wbs_code.count(".") + 1)
