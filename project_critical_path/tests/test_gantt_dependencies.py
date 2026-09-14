from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestGanttDependencies(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["project.project"].create({
            "name": "Dependency visualization", "allow_task_dependencies": True,
        })
        cls.tasks = cls.env["project.task"].create([
            {"name": name, "project_id": cls.project.id, "allocated_hours": 8}
            for name in ("Drawing", "Approval", "Procurement", "Installation")
        ])

    def test_visual_types_preserve_native_graph_and_schedule(self):
        first, second, third, fourth = self.tasks
        second.write({"depend_on_ids": [(4, first.id)]})
        third.write({"depend_on_ids": [(4, second.id)]})
        fourth.write({"depend_on_ids": [(4, third.id)]})
        before = self.tasks.read(["wbs_code", "critical_early_start", "critical_slack"])
        self.project.action_create_critical_path_baseline()
        baseline = self.project.critical_path_baseline_ids
        for kind in ("FS", "SS", "FF", "SF"):
            second.set_gantt_dependency(first.id, kind, -2.5)
            self.assertEqual(second.depend_on_ids, first)
            self.assertEqual(first.dependent_ids, second)
            self.assertEqual(second.gantt_dependency_metadata[str(first.id)], {
                "type": kind, "lag": -2.5,
            })
            self.assertEqual(self.tasks.read(["wbs_code", "critical_early_start", "critical_slack"]), before)
            self.assertEqual(baseline.project_duration, 32)

    def test_create_preserves_other_native_dependencies(self):
        first, second, third, fourth = self.tasks
        fourth.write({"depend_on_ids": [(4, first.id), (4, second.id)]})
        fourth.set_gantt_dependency(third.id, "SS", 2, create=True)
        self.assertEqual(set(fourth.depend_on_ids.ids), {first.id, second.id, third.id})
        fourth.remove_gantt_dependency(third.id)
        self.assertEqual(set(fourth.depend_on_ids.ids), {first.id, second.id})
        self.assertFalse(fourth.gantt_dependency_metadata)

    def test_reject_self_duplicate_cycle_and_bad_metadata(self):
        first, second, third, fourth = self.tasks
        second.set_gantt_dependency(first.id, create=True)
        third.set_gantt_dependency(second.id, create=True)
        for task, predecessor in ((first, first), (second, first), (first, third)):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                task.set_gantt_dependency(predecessor.id, create=True)
        for kind, lag in (("XX", 0), ("FS", float("nan")), ("FS", float("inf")), ("FS", "2")):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                second.set_gantt_dependency(first.id, kind, lag)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            fourth.write({"gantt_dependency_metadata": {str(first.id): {"type": "FS", "lag": 0}}})

    def test_native_removal_discards_only_removed_metadata(self):
        first, second, third, fourth = self.tasks
        fourth.set_gantt_dependency(first.id, "SS", 1, create=True)
        fourth.set_gantt_dependency(second.id, "FF", 2, create=True)
        first.write({"dependent_ids": [(3, fourth.id)]})
        self.assertNotIn(str(first.id), fourth.gantt_dependency_metadata)
        self.assertEqual(fourth.gantt_dependency_metadata[str(second.id)]["type"], "FF")
        fourth.write({"depend_on_ids": [(5, 0, 0)]})
        self.assertFalse(fourth.gantt_dependency_metadata)
        fourth.write({"depend_on_ids": [(4, second.id)]})
        self.assertFalse(fourth.gantt_dependency_metadata)

    def test_gantt_arch_keeps_existing_view_and_adds_native_fields(self):
        view = self.env["ir.ui.view"].create({
            "name": "Dependency test Gantt", "model": "project.task", "type": "gantt",
            "arch_db": '<gantt date_start="date_assign" date_stop="date_deadline" default_group_by="project_id"/>',
        })
        arch, _view = self.env["project.task"]._get_view(view.id, "gantt")
        self.assertEqual(arch.get("dependency_field"), "depend_on_ids")
        self.assertEqual(arch.get("dependency_inverted_field"), "dependent_ids")
        self.assertEqual(arch.get("default_group_by"), "project_id")
        self.assertEqual(len(arch.xpath("field[@name='gantt_dependency_metadata']")), 1)
