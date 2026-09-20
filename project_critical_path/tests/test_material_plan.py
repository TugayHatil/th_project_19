# -*- coding: utf-8 -*-

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestMaterialPlan(TransactionCase):
    """Material Plan (BRD) — project-scoped product lines on Task/WBS:
    required fields, duplicate prevention, quantity validation, project
    isolation, UoM default and product aggregation via read_group."""

    def setUp(self):
        super().setUp()
        Plan = self.env["project.material.plan"]
        self.plan_model = Plan
        self.project = self.env["project.project"].create({"name": "MP Project"})
        self.other_project = self.env["project.project"].create({"name": "Other"})
        self.task_a = self.env["project.task"].create({
            "name": "1.2 Cable Works", "project_id": self.project.id,
            "date_assign": "2026-10-01 09:00:00", "date_deadline": "2026-10-15 18:00:00",
        })
        self.task_b = self.env["project.task"].create({
            "name": "1.5 Other Works", "project_id": self.project.id,
        })
        self.other_task = self.env["project.task"].create({
            "name": "Foreign Task", "project_id": self.other_project.id,
        })
        self.product = self.env["product.product"].create({"name": "NYY 3x2.5"})
        self.product_b = self.env["product.product"].create({"name": "Cable Tray"})

    def _line(self, task=None, product=None, qty=10.0, **values):
        vals = {
            "project_id": self.project.id,
            "task_id": (task or self.task_a).id,
            "product_id": (product or self.product).id,
            "planned_quantity": qty,
        }
        vals.update(values)
        return self.plan_model.create(vals)

    def test_create_and_uom_default(self):
        line = self._line(qty=40.0)
        self.assertEqual(line.project_id, self.project)
        self.assertEqual(line.uom_id, self.product.uom_id)
        self.assertTrue(line.display_name)

    def test_required_date_defaults_to_task_deadline(self):
        line = self._line()
        self.assertEqual(str(line.required_date), "2026-10-15")

    def test_same_product_different_tasks(self):
        a = self._line(task=self.task_a, qty=40.0)
        b = self._line(task=self.task_b, qty=60.0)
        self.assertNotEqual(a.id, b.id)
        grouped = self.plan_model.read_group(
            [("project_id", "=", self.project.id), ("product_id", "=", self.product.id)],
            ["planned_quantity"], ["product_id"],
        )
        self.assertEqual(grouped[0]["planned_quantity"], 100.0)

    def test_duplicate_project_task_product_rejected(self):
        self._line(task=self.task_a)
        with self.assertRaises(ValidationError):
            self._line(task=self.task_a, qty=5.0)

    def test_quantity_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._line(qty=0.0)
        line = self._line()
        with self.assertRaises(ValidationError):
            line.planned_quantity = -10

    def test_task_must_belong_to_project(self):
        with self.assertRaises(ValidationError):
            self.plan_model.create({
                "project_id": self.project.id,
                "task_id": self.other_task.id,
                "product_id": self.product.id,
                "planned_quantity": 1.0,
            })

    def test_project_isolation(self):
        self._line()
        lines = self.plan_model.search([("project_id", "=", self.other_project.id)])
        self.assertFalse(lines)

    def test_planner_integration_same_task_source(self):
        # The material line references the very same project.task record
        # the Planner renders — no shadow task/WBS model is created.
        line = self._line(task=self.task_a)
        data = self.project.get_planner_data()
        planner_ids = {task["id"] for task in data["tasks"]}
        self.assertIn(line.task_id.id, planner_ids)
        self.assertEqual(line.task_id, self.task_a)
