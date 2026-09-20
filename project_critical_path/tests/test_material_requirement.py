# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestMaterialRequirement(TransactionCase):
    """Material Requirement (BRD phase 2) — SQL view over Material Plan lines
    aggregated per (Project, Product) against live stock availability:
    consolidation, shortage math, status, source traceability, UoM
    conversion and project isolation. Nothing downstream (PO/MO/picking)
    is ever created."""

    def setUp(self):
        super().setUp()
        self.plan_model = self.env["project.material.plan"]
        self.req_model = self.env["project.material.requirement"]
        self.project = self.env["project.project"].create({"name": "MR Project"})
        self.other_project = self.env["project.project"].create({"name": "Other"})
        self.task_a = self.env["project.task"].create({
            "name": "1.2 Cable Works", "project_id": self.project.id,
            "date_assign": "2026-10-01 09:00:00", "date_deadline": "2026-10-15 18:00:00",
        })
        self.task_b = self.env["project.task"].create({
            "name": "1.5 Other Works", "project_id": self.project.id,
            "date_deadline": "2026-10-20 18:00:00",
        })
        self.other_task = self.env["project.task"].create({
            "name": "Foreign Task", "project_id": self.other_project.id,
        })
        self.product = self.env["product.product"].create({"name": "NYY 3x2.5"})
        self.stock_location = self.env.ref("stock.stock_location_stock")

    def _line(self, task=None, product=None, qty=10.0, project=None, **values):
        vals = {
            "project_id": (project or self.project).id,
            "task_id": (task or self.task_a).id,
            "product_id": (product or self.product).id,
            "planned_quantity": qty,
        }
        vals.update(values)
        return self.plan_model.create(vals)

    def _set_stock(self, product, qty):
        quant = self.env["stock.quant"].search([
            ("product_id", "=", product.id),
            ("location_id", "=", self.stock_location.id),
        ], limit=1)
        if quant:
            quant.quantity = qty
        else:
            quant = self.env["stock.quant"].create({
                "product_id": product.id,
                "location_id": self.stock_location.id,
                "quantity": qty,
            })
        return quant

    def _req(self, product=None, project=None):
        return self.req_model.search([
            ("project_id", "=", (project or self.project).id),
            ("product_id", "=", (product or self.product).id),
        ])

    def test_aggregation_per_project_product(self):
        self._line(task=self.task_a, qty=40.0)
        self._line(task=self.task_b, qty=60.0)
        requirement = self._req()
        self.assertEqual(len(requirement), 1)
        self.assertEqual(requirement.planned_quantity, 100.0)
        self.assertEqual(requirement.uom_id, self.product.uom_id)

    def test_available_and_shortage(self):
        self._line(qty=100.0)
        self._set_stock(self.product, 60.0)
        requirement = self._req()
        self.assertEqual(requirement.available_quantity, 60.0)
        self.assertEqual(requirement.shortage_quantity, 40.0)
        self.assertEqual(requirement.status, "partially_available")

    def test_fully_available(self):
        self._line(qty=100.0)
        self._set_stock(self.product, 120.0)
        requirement = self._req()
        self.assertEqual(requirement.shortage_quantity, 0.0)
        self.assertEqual(requirement.status, "available")

    def test_not_available(self):
        self._line(qty=100.0)
        requirement = self._req()
        self.assertEqual(requirement.available_quantity, 0.0)
        self.assertEqual(requirement.shortage_quantity, 100.0)
        self.assertEqual(requirement.status, "not_available")

    def test_plan_quantity_update_is_live(self):
        line = self._line(qty=100.0)
        self._set_stock(self.product, 60.0)
        line.planned_quantity = 120.0
        requirement = self._req()
        self.assertEqual(requirement.planned_quantity, 120.0)
        self.assertEqual(requirement.shortage_quantity, 60.0)

    def test_stock_update_is_live(self):
        self._line(qty=100.0)
        quant = self._set_stock(self.product, 60.0)
        self.assertEqual(self._req().shortage_quantity, 40.0)
        quant.quantity = 90.0
        requirement = self._req()
        self.assertEqual(requirement.available_quantity, 90.0)
        self.assertEqual(requirement.shortage_quantity, 10.0)
        quant.quantity = 150.0
        self.assertEqual(self._req().status, "available")

    def test_no_duplicate_requirement_rows(self):
        self._line(task=self.task_a, qty=40.0)
        self._line(task=self.task_b, qty=60.0)
        product_c = self.env["product.product"].create({"name": "Panel"})
        self._line(task=self.task_b, product=product_c, qty=5.0)
        self.assertEqual(len(self._req()), 1)
        self.assertEqual(
            len(self.req_model.search([("project_id", "=", self.project.id)])), 2,
        )

    def test_source_lines_traceability(self):
        line_a = self._line(task=self.task_a, qty=40.0)
        line_b = self._line(task=self.task_b, qty=60.0)
        requirement = self._req()
        self.assertEqual(
            set(requirement.material_plan_line_ids.ids), {line_a.id, line_b.id},
        )
        self.assertEqual(str(requirement.required_date), "2026-10-15")
        self.assertEqual(
            sorted(str(d) for d in requirement.material_plan_line_ids.mapped("required_date")),
            ["2026-10-15", "2026-10-20"],
        )

    def test_project_isolation(self):
        self._line(qty=40.0)
        self._line(
            task=self.other_task, project=self.other_project, qty=99.0,
        )
        own = self._req()
        self.assertEqual(own.planned_quantity, 40.0)
        foreign = self._req(project=self.other_project)
        self.assertEqual(foreign.planned_quantity, 99.0)

    def test_uom_conversion(self):
        km = self.env["uom.uom"].search([("name", "=", "km")], limit=1)
        m = self.env["uom.uom"].search([("name", "=", "m")], limit=1)
        if not (km and m) or self.product.uom_id != m:
            self.skipTest("km/m UoM data not available")
        self._line(task=self.task_a, qty=40.0)
        self._line(task=self.task_b, qty=0.06, uom_id=km.id)
        requirement = self._req()
        self.assertAlmostEqual(requirement.planned_quantity, 100.0)
        self.assertEqual(requirement.uom_id, m)

    def test_status_group_by_and_filters(self):
        self._line(task=self.task_a, qty=40.0)
        product_b = self.env["product.product"].create({"name": "Panel"})
        self._line(task=self.task_b, product=product_b, qty=5.0)
        self._set_stock(product_b, 10.0)
        grouped = self.req_model.read_group(
            [("project_id", "=", self.project.id)],
            ["planned_quantity"], ["status"],
        )
        by_status = {g["status"]: g["status_count"] for g in grouped}
        self.assertEqual(by_status.get("not_available"), 1)
        self.assertEqual(by_status.get("available"), 1)
        self.assertEqual(
            len(self.req_model.search([
                ("project_id", "=", self.project.id),
                ("status", "=", "available"),
            ])),
            1,
        )

    def test_status_is_read_only(self):
        self._line(qty=100.0)
        requirement = self._req()
        with self.assertRaises(Exception):
            requirement.write({"status": "available"})

    def test_no_execution_documents_created(self):
        self._line(qty=100.0)
        self.assertFalse(self.env["purchase.order"].search([
            ("order_line.product_id", "=", self.product.id),
        ]))
        self.assertFalse(self.env["stock.picking"].search([
            ("move_ids.product_id", "=", self.product.id),
        ]))
