# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from odoo import fields


class TestMaterialRisk(TransactionCase):
    """BRD TEST-MAT-001..010 — line availability states, task-level risk
    aggregation and the downstream/project-finish projection built on the
    existing dependency graph (no second CPM engine)."""

    def setUp(self):
        super().setUp()
        self.Plan = self.env["project.material.plan"]
        self.stock_location = self.env.ref("stock.stock_location_stock")
        self.dest_location = self.env["stock.location"].create({
            "name": "WH/Projects/PEC", "usage": "internal",
            "location_id": self.stock_location.location_id.id,
        })
        self.project = self.env["project.project"].create({
            "name": "MAT Project",
            "material_source_location_id": self.stock_location.id,
            "material_destination_location_id": self.dest_location.id,
        })
        self.product = self.env["product.product"].create({
            "name": "PEC Material", "is_storable": True,
        })
        # A → B → C is the single chain (all critical); D floats free so
        # it carries slack against the project duration.
        self.task_a = self._task("A", "2026-10-01 09:00:00",
                                 "2026-10-01 17:00:00")
        self.task_b = self._task("B", "2026-10-02 09:00:00",
                                 "2026-10-02 17:00:00")
        self.task_c = self._task("C", "2026-10-03 09:00:00",
                                 "2026-10-03 17:00:00")
        self.task_d = self._task("D (float)", "2026-10-01 09:00:00",
                                 "2026-10-01 17:00:00")
        self.task_b.depend_on_ids = [fields.Command.link(self.task_a.id)]
        self.task_c.depend_on_ids = [fields.Command.link(self.task_b.id)]

    # ── helpers ──────────────────────────────────────────────────────
    def _task(self, name, start, end, hours=8.0):
        return self.env["project.task"].create({
            "name": name,
            "project_id": self.project.id,
            "date_assign": start,
            "date_deadline": end,
            "allocated_hours": hours,
        })

    def _line(self, task, qty=10.0, required_date="2026-10-01", **values):
        return self.Plan.create({
            "project_id": self.project.id,
            "task_id": task.id,
            "product_id": self.product.id,
            "planned_quantity": qty,
            "required_date": required_date,
            **values,
        })

    def _stock(self, qty):
        """Physical on-hand at the plan's source location."""
        self.env["stock.quant"].create({
            "product_id": self.product.id,
            "location_id": self.stock_location.id,
            "quantity": qty,
        })

    def _approve(self, line):
        line.action_approve()
        line.move_ids.picking_id.action_assign()
        line.invalidate_recordset()
        return line

    # ── Line-level availability states ───────────────────────────────
    def test_mat_001_fully_available_no_risk(self):
        """TEST-MAT-001 — stock covers the requirement on time."""
        self._stock(20.0)
        line = self._approve(self._line(self.task_a, qty=10.0))
        self.assertEqual(line.material_state, "ready")
        self.assertEqual(line.shortage_quantity, 0.0)
        self.assertEqual(line.material_delay_days, 0.0)
        self.assertEqual(self.task_a.material_risk, "no_risk")

    def test_mat_002_partial_availability(self):
        """TEST-MAT-002 — only part of the quantity can be promised."""
        self._stock(4.0)
        line = self._approve(self._line(self.task_a, qty=10.0))
        self.assertEqual(line.material_state, "partial")
        self.assertAlmostEqual(line.available_quantity, 4.0, places=2)
        self.assertAlmostEqual(line.shortage_quantity, 6.0, places=2)
        self.assertEqual(self.task_a.material_risk, "partial")

    def test_mat_003_availability_after_required_delay(self):
        """TEST-MAT-003 — expected availability lands after the required
        date → the line reads delayed by the day delta."""
        line = self._approve(self._line(
            self.task_d, qty=10.0, required_date="2026-10-01"))
        # Push the transfer's scheduled date 5 days past the requirement —
        # Odoo can no longer promise on-time availability.
        line.move_ids.date = fields.Datetime.to_datetime("2026-10-06")
        line.invalidate_recordset()
        self.assertEqual(line.material_state, "delayed")
        self.assertAlmostEqual(line.material_delay_days, 5.0, delta=1.0)
        self.assertIn(self.task_d.material_risk, ("delayed", "critical"))

    def test_mat_008_full_quantity_no_false_shortage(self):
        """TEST-MAT-008 — a fully covered line must not report a phantom
        shortage or delay."""
        self._stock(10.0)
        line = self._approve(self._line(self.task_a, qty=10.0))
        self.assertEqual(line.shortage_quantity, 0.0)
        self.assertEqual(line.material_delay_days, 0.0)
        self.assertEqual(line.material_state, "ready")

    def test_mat_009_unknown_date_never_available(self):
        """TEST-MAT-009 — a draft line has no stock data at all; it must
        never read as available."""
        line = self._line(self.task_a)
        self.assertEqual(line.material_state, "unknown")
        self.assertEqual(line.available_quantity, 0.0)
        self.assertEqual(line.shortage_quantity, line.planned_quantity)
        self.assertEqual(self.task_a.material_risk, "delayed")

    def test_mat_010_no_requirement_no_risk(self):
        """TEST-MAT-010 — tasks without material lines carry no risk."""
        self.assertFalse(self.task_a.material_plan_line_ids)
        self.assertEqual(self.task_a.material_risk, "no_risk")
        self.assertEqual(self.task_a.material_delay_days, 0.0)
        self.assertEqual(self.task_a.material_project_impact_days, 0.0)

    # ── Dependency propagation & project finish ──────────────────────
    def test_mat_004_downstream_impact(self):
        """TEST-MAT-004 — a material delay on A ripples through the
        A → B → C chain over the shared dependency graph."""
        line = self._approve(self._line(
            self.task_a, qty=10.0, required_date="2026-10-01"))
        line.move_ids.date = fields.Datetime.to_datetime("2026-10-06")
        line.invalidate_recordset()
        task_a = self.task_a
        task_a.invalidate_recordset()
        self.assertEqual(task_a.material_downstream_count, 2)
        self.assertAlmostEqual(
            task_a.material_downstream_impact_days, 5.0, delta=1.0)
        # B and C were not written — the projection is informational.
        self.assertEqual(str(self.task_b.date_assign),
                         "2026-10-02 09:00:00")

    def test_mat_005_critical_path_impact(self):
        """TEST-MAT-005 — delaying the critical chain moves the projected
        project finish by the same amount."""
        line = self._approve(self._line(
            self.task_a, qty=10.0, required_date="2026-10-01"))
        line.move_ids.date = fields.Datetime.to_datetime("2026-10-06")
        line.invalidate_recordset()
        self.task_a.invalidate_recordset()
        self.project.invalidate_recordset()
        self.assertEqual(self.task_a.material_risk, "critical")
        self.assertAlmostEqual(
            self.task_a.material_project_impact_days, 5.0, delta=1.0)
        self.assertAlmostEqual(
            self.project.material_finish_impact_days, 5.0, delta=1.0)
        self.assertEqual(str(self.project.material_planned_finish),
                         "2026-10-03")
        self.assertAlmostEqual(
            (fields.Date.to_date(self.project.material_projected_finish)
             - fields.Date.to_date("2026-10-03")).days, 5, delta=1)

    def test_mat_006_noncritical_delay_no_finish_impact(self):
        """TEST-MAT-006 — the floating task D has slack; its material
        delay must surface as risk without inflating project finish."""
        line = self._approve(self._line(
            self.task_d, qty=10.0, required_date="2026-10-01"))
        line.move_ids.date = fields.Datetime.to_datetime("2026-10-02")
        line.invalidate_recordset()
        self.task_d.invalidate_recordset()
        self.assertNotEqual(self.task_d.material_risk, "no_risk")
        self.assertNotEqual(self.task_d.material_risk, "critical")
        self.assertEqual(self.task_d.material_downstream_count, 0)
        self.assertEqual(self.task_d.material_project_impact_days, 0.0)

    def test_mat_007_shared_material_no_double_count(self):
        """TEST-MAT-007 — two tasks requiring the same product share the
        physical stock; availability is never allocated twice."""
        self._stock(12.0)
        line_a = self._line(self.task_a, qty=10.0)
        line_b = self._line(self.task_b, qty=10.0)
        self._approve(line_a | line_b)
        total = line_a.available_quantity + line_b.available_quantity
        self.assertAlmostEqual(total, 12.0, places=2)
        # 10 + 2 — whichever move reserved first wins; the other reads
        # short. Both can never read "ready" off 12 units.
        self.assertNotEqual(
            {line_a.material_state, line_b.material_state}, {"ready"})

    # ── Search support & payload ─────────────────────────────────────
    def test_material_risk_search_domain(self):
        """The non-stored risk field stays usable in domains/filters."""
        line = self._line(self.task_a)
        self.task_a.invalidate_recordset()
        risky = self.env["project.task"].search(
            [("material_risk", "!=", "no_risk")])
        self.assertIn(self.task_a, risky)
        self.assertNotIn(self.task_c, risky)
        self.assertEqual(line.material_state, "unknown")

    def test_planner_payload_material_keys(self):
        """get_planner_data rows carry the material block — the same
        post-processing point that survived the super() shadowing issue."""
        self._line(self.task_a)
        data = self.project.get_planner_data()
        rows = {row["id"]: row for row in data["tasks"]}
        row = rows[self.task_a.id]
        for key in ("material_risk", "material_delay_days",
                    "material_project_impact_days",
                    "material_downstream_count",
                    "material_shortage_quantity"):
            self.assertIn(key, row)
        self.assertEqual(row["material_risk"], "delayed")
        detail = self.task_a.get_planner_detail()
        self.assertIn("material", detail)
        self.assertEqual(len(detail["material"]["lines"]), 1)
