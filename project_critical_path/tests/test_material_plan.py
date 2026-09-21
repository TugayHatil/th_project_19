# -*- coding: utf-8 -*-

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestMaterialPlan(TransactionCase):
    """Material Plan → Odoo Stock (BRD): project-scoped draft/approved
    lifecycle. Approving draft lines creates standard stock.picking /
    stock.move grouped by (source, destination); reservation and
    replenishment stay standard Odoo — no custom procurement."""

    def setUp(self):
        super().setUp()
        Plan = self.env["project.material.plan"]
        self.plan_model = Plan
        self.stock_location = self.env.ref("stock.stock_location_stock")
        self.other_location = self.env["stock.location"].create({
            "name": "WH/Other", "usage": "internal",
            "location_id": self.stock_location.location_id.id,
        })
        self.dest_location = self.env["stock.location"].create({
            "name": "WH/Projects/Project A", "usage": "internal",
            "location_id": self.stock_location.location_id.id,
        })
        self.project = self.env["project.project"].create({
            "name": "MP Project",
            "material_source_location_id": self.stock_location.id,
            "material_destination_location_id": self.dest_location.id,
        })
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
        self.product = self.env["product.product"].create({
            "name": "NYY 3x2.5", "is_storable": True,
        })
        self.product_b = self.env["product.product"].create({
            "name": "Cable Tray", "is_storable": True,
        })
        self.service_product = self.env["product.product"].create({
            "name": "Consulting", "is_storable": False,
        })
        Picking = self.env["stock.picking"]
        Move = self.env["stock.move"]
        self._picking_count = lambda: Picking.search_count([
            ("move_ids.material_plan_line_id.project_id", "=", self.project.id)])
        self._move_model = Move

    def _line(self, task=None, product=None, qty=10.0, **values):
        vals = {
            "project_id": self.project.id,
            "task_id": (task or self.task_a).id,
            "product_id": (product or self.product).id,
            "planned_quantity": qty,
        }
        vals.update(values)
        return self.plan_model.create(vals)

    # ── Defaults ─────────────────────────────────────────────────────
    def test_material_plan_defaults(self):
        line = self._line(qty=40.0)
        self.assertEqual(line.state, "draft")
        self.assertEqual(line.uom_id, self.product.uom_id)
        self.assertEqual(str(line.required_date), "2026-10-15")
        self.assertEqual(line.source_location_id, self.stock_location)
        self.assertEqual(line.destination_location_id, self.dest_location)

    def test_material_plan_location_override(self):
        line = self._line(source_location_id=self.other_location.id)
        self.assertEqual(line.source_location_id, self.other_location)
        self.assertEqual(self.project.material_source_location_id, self.stock_location)

    # ── Validations ──────────────────────────────────────────────────
    def test_material_plan_task_project_validation(self):
        with self.assertRaises(ValidationError):
            self.plan_model.create({
                "project_id": self.project.id,
                "task_id": self.other_task.id,
                "product_id": self.product.id,
                "planned_quantity": 1.0,
            })

    def test_quantity_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self._line(qty=0.0)
        line = self._line()
        with self.assertRaises(ValidationError):
            line.planned_quantity = -10

    def test_non_storable_product_rejected(self):
        with self.assertRaises(ValidationError):
            self._line(product=self.service_product)

    def test_duplicate_product_is_allowed(self):
        a = self._line(qty=100.0)
        b = self._line(task=self.task_b, qty=30.0)
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(a.product_id, b.product_id)

    def test_project_isolation(self):
        self._line()
        lines = self.plan_model.search([("project_id", "=", self.other_project.id)])
        self.assertFalse(lines)

    # ── Draft ────────────────────────────────────────────────────────
    def test_material_plan_draft_no_picking(self):
        line = self._line(qty=100.0)
        self.assertEqual(line.state, "draft")
        self.assertFalse(line.move_ids)
        self.assertFalse(line.picking_ids)
        self.assertFalse(line.move_ids.picking_id)
        self.assertEqual(self._picking_count(), 0)

    # ── Approval ─────────────────────────────────────────────────────
    def test_material_plan_approval_creates_picking(self):
        line = self._line(qty=100.0)
        line.action_approve()
        self.assertEqual(line.state, "approved")
        self.assertEqual(len(line.picking_ids), 1)
        picking = line.picking_ids
        self.assertEqual(picking.picking_type_id.code, "internal")
        self.assertEqual(picking.location_id, self.stock_location)
        self.assertEqual(picking.location_dest_id, self.dest_location)
        self.assertEqual(len(picking.move_ids), 1)
        move = picking.move_ids
        self.assertEqual(move.product_id, self.product)
        self.assertEqual(move.product_uom_qty, 100.0)
        self.assertEqual(move.product_uom, self.product.uom_id)
        self.assertEqual(move.material_plan_line_id, line)
        # required_date carried onto the move's scheduled date
        self.assertEqual(str(move.date.date()), "2026-10-15")

    def test_material_plan_same_source_single_picking(self):
        a = self._line(qty=100.0)
        b = self._line(task=self.task_b, product=self.product_b, qty=10.0)
        (a | b).action_approve()
        self.assertEqual(a.picking_ids, b.picking_ids)
        self.assertEqual(len(a.picking_ids.move_ids), 2)

    def test_material_plan_different_source_multiple_pickings(self):
        a = self._line(qty=100.0)
        b = self._line(task=self.task_b, product=self.product_b, qty=10.0,
                       source_location_id=self.other_location.id)
        (a | b).action_approve()
        self.assertNotEqual(a.picking_ids, b.picking_ids)
        self.assertEqual(len(a.picking_ids | b.picking_ids), 2)

    def test_material_plan_grouping_by_source_destination(self):
        a = self._line(qty=100.0)
        b = self._line(task=self.task_b, product=self.product_b, qty=10.0)
        c = self._line(task=self.task_b, product=self.product, qty=50.0,
                       source_location_id=self.other_location.id)
        (a | b | c).action_approve()
        pickings = (a | b | c).picking_ids
        self.assertEqual(len(pickings), 2)
        self.assertEqual(a.picking_ids, b.picking_ids)
        self.assertNotEqual(c.picking_ids, a.picking_ids)

    def test_approve_twice_noop(self):
        line = self._line()
        line.action_approve()
        with self.assertRaises(UserError):
            line.action_approve()

    # ── Approved lines are read-only / new need = new line ───────────
    def test_material_plan_approved_readonly(self):
        line = self._line(qty=100.0)
        line.action_approve()
        with self.assertRaises(UserError):
            line.write({"planned_quantity": 130.0})
        with self.assertRaises(UserError):
            line.write({"product_id": self.product_b.id})
        with self.assertRaises(UserError):
            line.write({"task_id": self.task_b.id})

    def test_material_plan_new_requirement(self):
        first = self._line(qty=100.0)
        first.action_approve()
        second = self._line(task=self.task_b, qty=30.0)
        self.assertEqual(second.state, "draft")
        self.assertEqual(first.planned_quantity, 100.0)
        self.assertEqual(len(first.picking_ids), 1)
        second.action_approve()
        self.assertEqual(first.planned_quantity, 100.0)
        self.assertNotEqual(first.picking_ids, second.picking_ids)

    # ── Traceability ─────────────────────────────────────────────────
    def test_material_plan_traceability(self):
        line = self._line(qty=100.0)
        line.action_approve()
        picking = line.picking_ids
        self.assertTrue(picking)
        # plan → picking
        action = line.action_open_transfers()
        self.assertEqual(action["res_model"], "stock.picking")
        # picking → plan
        self.assertIn(line, picking.material_plan_line_ids)
        self.assertIn("MP", (picking.origin or "") or "MP")
        self.assertIn("Material Plan", picking.origin or "")

    # ── UI navigation (BRD: Material Plan → Odoo Transfer) ──────────
    def test_single_picking_navigation(self):
        line = self._line(qty=100.0)
        line.action_approve()
        action = line.action_open_transfers()
        self.assertEqual(action["res_model"], "stock.picking")
        self.assertEqual(action["res_id"], line.picking_ids.id)
        self.assertEqual(action["views"], [[False, "form"]])

    def test_multiple_picking_navigation(self):
        a = self._line(qty=100.0)
        b = self._line(task=self.task_b, product=self.product_b, qty=10.0,
                       source_location_id=self.other_location.id)
        (a | b).action_approve()
        action = (a | b).action_open_transfers()
        self.assertEqual(action["res_model"], "stock.picking")
        domain_ids = next(v for f, _, v in action["domain"] if f == "id")
        self.assertEqual(set(domain_ids), set((a | b).picking_ids.ids))
        self.assertEqual(len(domain_ids), 2)
        self.assertEqual(action["views"], [[False, "list"], [False, "form"]])

    def test_project_picking_isolation(self):
        a = self._line(qty=100.0)
        b = self._line(task=self.task_b, product=self.product_b, qty=10.0,
                       source_location_id=self.other_location.id)
        (a | b).action_approve()
        other_line = self.plan_model.create({
            "project_id": self.other_project.id,
            "task_id": self.other_task.id,
            "product_id": self.product.id,
            "planned_quantity": 5.0,
            "source_location_id": self.stock_location.id,
            "destination_location_id": self.dest_location.id,
        })
        other_line.action_approve()
        action = self.project.action_open_material_transfers()
        self.assertEqual(action["res_model"], "stock.picking")
        domain_ids = next(v for f, _, v in action["domain"] if f == "id")
        self.assertEqual(set(domain_ids), set((a | b).picking_ids.ids))
        self.assertNotIn(other_line.picking_ids.id, domain_ids)

    def test_material_plan_line_picking_relation(self):
        line = self._line(qty=100.0)
        line.action_approve()
        picking = line.picking_ids
        self.assertEqual(line.picking_id, picking)
        self.assertEqual(line.picking_count, 1)
        self.assertEqual(line.move_ids.picking_id, picking)
        self.assertEqual(picking.move_ids.material_plan_line_id, line)
        self.assertIn(line, picking.material_plan_line_ids)

    # ── Editable-list planning UX (BRD: List-first Material Plan) ────
    def test_material_plan_list_action(self):
        action = self.env.ref("project_critical_path.action_project_material_plan")
        self.assertEqual(action.view_mode.split(",")[0], "list")
        project_action = self.project.action_open_material_plan()
        self.assertEqual(project_action["view_mode"], "list,form")
        arch = self.env.ref(
            "project_critical_path.project_material_plan_list").arch_db
        self.assertIn('editable="bottom"', arch)

    def test_draft_line_inline_edit(self):
        """Inline edits on a draft line are plain writes — no form needed,
        no picking created."""
        line = self._line(qty=100.0)
        line.write({"planned_quantity": 120.0})
        line.write({
            "product_id": self.product_b.id,
            "task_id": self.task_b.id,
            "required_date": "2027-01-01",
            "source_location_id": self.other_location.id,
            "destination_location_id": self.dest_location.id,
        })
        line.invalidate_recordset()
        self.assertEqual(line.planned_quantity, 120.0)
        self.assertEqual(line.product_id, self.product_b)
        self.assertEqual(line.task_id, self.task_b)
        self.assertEqual(str(line.required_date), "2027-01-01")
        self.assertEqual(line.source_location_id, self.other_location)
        self.assertEqual(line.state, "draft")
        self.assertFalse(line.move_ids)

    def test_draft_defaults(self):
        """Minimal inline create (project + task + product only) still gets
        project locations, product UoM and task deadline defaults."""
        line = self.plan_model.create({
            "project_id": self.project.id,
            "task_id": self.task_a.id,
            "product_id": self.product.id,
            "planned_quantity": 5.0,
        })
        self.assertEqual(line.source_location_id, self.stock_location)
        self.assertEqual(line.destination_location_id, self.dest_location)
        self.assertEqual(line.uom_id, self.product.uom_id)
        self.assertEqual(str(line.required_date), "2026-10-15")

    def test_approved_line_immutable(self):
        line = self._line(qty=100.0)
        line.action_approve()
        for vals in (
            {"planned_quantity": 130.0},
            {"product_id": self.product_b.id},
            {"task_id": self.task_b.id},
            {"required_date": "2027-01-01"},
            {"source_location_id": self.other_location.id},
            {"destination_location_id": self.stock_location.id},
        ):
            with self.assertRaises(UserError):
                line.write(vals)
        with self.assertRaises(UserError):
            line.unlink()

    def test_bulk_approval(self):
        """Selecting a mixed recordset only approves the drafts; grouping
        rules still apply inside the same approval call."""
        a = self._line(qty=100.0)
        b = self._line(task=self.task_b, product=self.product_b, qty=50.0)
        c = self._line(task=self.task_b, qty=30.0,
                       source_location_id=self.other_location.id)
        d = self._line(qty=5.0)
        d.action_approve()
        (a | b | c | d).action_approve()
        self.assertEqual(set((a | b | c).mapped("state")), {"approved"})
        self.assertEqual(a.picking_ids, b.picking_ids)
        self.assertNotEqual(c.picking_ids, a.picking_ids)
        self.assertEqual(len((a | b | c | d).picking_ids), 3)

    def test_transfer_navigation_relation(self):
        line = self._line(qty=100.0)
        line.action_approve()
        self.assertEqual(line.picking_id, line.picking_ids)
        action = line.action_open_transfers()
        self.assertEqual(action["res_model"], "stock.picking")
        self.assertEqual(action["res_id"], line.picking_ids.id)

    def test_material_picking_count(self):
        """Badge counter: 0 on draft, tracks linked pickings on approve."""
        line = self._line(qty=100.0)
        self.assertEqual(line.picking_count, 0)
        line.action_approve()
        self.assertEqual(line.picking_count, 1)
        # A second (forced) move on another picking raises the badge count
        other_picking = self.env["stock.picking"].create({
            "picking_type_id": line.picking_ids.picking_type_id.id,
            "location_id": self.other_location.id,
            "location_dest_id": self.dest_location.id,
        })
        self.env["stock.move"].create({
            "name": self.product_b.display_name,
            "product_id": self.product_b.id,
            "product_uom_qty": 10.0,
            "product_uom": self.product_b.uom_id.id,
            "location_id": self.other_location.id,
            "location_dest_id": self.dest_location.id,
            "picking_id": other_picking.id,
            "material_plan_line_id": line.id,
        })
        line.invalidate_recordset()
        self.assertEqual(line.picking_count, 2)
        action = line.action_open_transfers()
        domain_ids = next(v for f, _, v in action["domain"] if f == "id")
        self.assertEqual(len(domain_ids), 2)

    # ── UoM / planner integration ────────────────────────────────────
    def test_uom_carried_to_move(self):
        uom_km = self.env["uom.uom"].search([
            ("name", "=", "km")], limit=1)
        if not uom_km:
            self.skipTest("km UoM not installed")
        line = self._line(qty=0.1, uom_id=uom_km.id)
        line.action_approve()
        move = line.move_ids
        self.assertEqual(move.product_uom, uom_km)
        self.assertEqual(move.product_uom_qty, 0.1)

    def test_planner_integration_same_task_source(self):
        line = self._line(task=self.task_a)
        data = self.project.get_planner_data()
        planner_ids = {task["id"] for task in data["tasks"]}
        self.assertIn(line.task_id.id, planner_ids)
        self.assertEqual(line.task_id, self.task_a)
