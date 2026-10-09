# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestComponentAlternative(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.groups_id += cls.env.ref(
            "mrp_component_alternative.group_alternative_selector")
        Product = cls.env["product.product"]
        cls.finished = Product.create({
            "name": "Finished Bike",
            "type": "consu",
            "is_storable": True,
        })
        cls.main = Product.create({
            "name": "A Jant",
            "type": "consu",
            "is_storable": True,
        })
        cls.alt_low = Product.create({
            "name": "B Jant",
            "type": "consu",
            "is_storable": True,
        })
        cls.alt_high = Product.create({
            "name": "C Jant",
            "type": "consu",
            "is_storable": True,
        })
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.finished.product_tmpl_id.id,
            "product_qty": 1.0,
            "bom_line_ids": [Command.create({
                "product_id": cls.main.id,
                "product_qty": 2.0,
            })],
        })
        cls.bom_line = cls.bom.bom_line_ids
        cls.Alternative = cls.env["mrp.bom.line.alternative"]
        cls.alt_low_def = cls.Alternative.create({
            "bom_line_id": cls.bom_line.id,
            "alternative_product_id": cls.alt_low.id,
            "sequence": 10,
        })
        cls.alt_high_def = cls.Alternative.create({
            "bom_line_id": cls.bom_line.id,
            "alternative_product_id": cls.alt_high.id,
            "sequence": 20,
        })
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1)
        cls.stock = warehouse.lot_stock_id
        cls.Quant = cls.env["stock.quant"]

    def _set_stock(self, product, qty):
        self.env["stock.quant"]._update_available_quantity(
            product, self.stock, qty)

    def _make_mo(self):
        mo = self.env["mrp.production"].create({
            "product_id": self.finished.id,
            "bom_id": self.bom.id,
            "product_qty": 1.0,
            "location_src_id": self.stock.id,
        })
        mo.action_confirm()
        return mo

    def _open_wizard(self, mo):
        action = mo.action_open_alternative_selector()
        return self.env["mrp.alternative.selector"].browse(action["res_id"])

    # ------------------------------------------------------------------
    # Definition rules
    # ------------------------------------------------------------------
    def test_alternative_count(self):
        self.assertEqual(self.bom_line.alternative_count, 2)
        self.alt_low_def.active = False
        self.assertEqual(self.bom_line.alternative_count, 1)

    def test_same_product_forbidden(self):
        with self.assertRaises(ValidationError):
            self.Alternative.create({
                "bom_line_id": self.bom_line.id,
                "alternative_product_id": self.main.id,
            })

    def test_duplicate_alternative_forbidden(self):
        with self.assertRaises(Exception):
            self.Alternative.create({
                "bom_line_id": self.bom_line.id,
                "alternative_product_id": self.alt_low.id,
            })

    def test_different_uom_category_forbidden(self):
        kg = self.env["product.product"].create({
            "name": "Steel (kg)", "type": "consu", "is_storable": True,
            "uom_id": self.env.ref("uom.product_uom_kgm").id,
        })
        with self.assertRaises(ValidationError):
            self.Alternative.create({
                "bom_line_id": self.bom_line.id,
                "alternative_product_id": kg.id,
            })

    # ------------------------------------------------------------------
    # Replenishment icon
    # ------------------------------------------------------------------
    def test_orderpoint_flag(self):
        orderpoint = self.env["stock.warehouse.orderpoint"].create({
            "product_id": self.main.id,
            "location_id": self.stock.id,
        })
        self.assertTrue(orderpoint.has_bom_alternatives)
        other = self.env["stock.warehouse.orderpoint"].create({
            "product_id": self.finished.id,
            "location_id": self.stock.id,
        })
        self.assertFalse(other.has_bom_alternatives)

    # ------------------------------------------------------------------
    # Selection wizard (BRD example: need 2, B has 1, C has 10 → C wins)
    # ------------------------------------------------------------------
    def test_suggested_alternative(self):
        self._set_stock(self.alt_low, 1.0)
        self._set_stock(self.alt_high, 10.0)
        mo = self._make_mo()
        wizard = self._open_wizard(mo)
        original = wizard.line_ids.filtered("is_original")
        self.assertFalse(original.can_cover)
        low = wizard.line_ids.filtered(
            lambda l: l.alternative_product_id == self.alt_low)
        high = wizard.line_ids.filtered(
            lambda l: l.alternative_product_id == self.alt_high)
        self.assertFalse(low.can_cover)
        self.assertFalse(low.is_suggested)
        self.assertTrue(high.can_cover)
        self.assertTrue(high.is_suggested)
        self.assertTrue(high.selected)

    def test_main_sufficient_no_suggestion(self):
        self._set_stock(self.main, 5.0)
        mo = self._make_mo()
        wizard = self._open_wizard(mo)
        self.assertFalse(wizard.line_ids.filtered("is_suggested"))
        original = wizard.line_ids.filtered("is_original")
        self.assertTrue(original.can_cover)
        self.assertTrue(original.selected)

    def test_no_alternative_covers(self):
        self._set_stock(self.alt_low, 1.0)
        mo = self._make_mo()
        wizard = self._open_wizard(mo)
        self.assertFalse(wizard.line_ids.filtered("is_suggested"))
        self.assertTrue(wizard.warning_message)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def test_apply_substitutes_move(self):
        self._set_stock(self.alt_high, 10.0)
        mo = self._make_mo()
        wizard = self._open_wizard(mo)
        wizard.action_apply()
        move = mo.move_raw_ids
        self.assertEqual(move.product_id, self.alt_high)
        self.assertTrue(move.is_alternative_component)
        self.assertEqual(move.original_product_id, self.main)
        self.assertEqual(move.alternative_selected_by, self.env.user)
        self.assertTrue(move.alternative_selected_date)
        # reservation is made on the alternative, not on the main product
        self.assertEqual(
            self.Quant._get_available_quantity(self.alt_high, self.stock), 8.0)
        self.assertEqual(
            len(mo.message_ids.filtered(
                lambda m: "Alternative component" in (m.body or ""))), 1)

    def test_apply_reverts_to_original(self):
        self._set_stock(self.main, 5.0)
        self._set_stock(self.alt_high, 10.0)
        mo = self._make_mo()
        move = mo.move_raw_ids
        move._apply_alternative_product(self.alt_high)
        self.assertEqual(move.product_id, self.alt_high)
        # reopen the wizard and select the original product again
        action = move.action_open_alternative_selector()
        wizard = self.env["mrp.alternative.selector"].browse(action["res_id"])
        wizard.line_ids.write({"selected": False})
        wizard.line_ids.filtered("is_original").selected = True
        wizard.action_apply()
        self.assertEqual(move.product_id, self.main)
        self.assertFalse(move.is_alternative_component)

    def test_apply_blocked_when_stock_changed(self):
        self._set_stock(self.alt_high, 10.0)
        mo = self._make_mo()
        wizard = self._open_wizard(mo)
        # stock disappears between evaluation and confirmation
        self.Quant._update_available_quantity(
            self.alt_high, self.stock, -10.0)
        with self.assertRaises(UserError):
            wizard.action_apply()
        self.assertEqual(mo.move_raw_ids.product_id, self.main)

    def test_apply_done_move_forbidden(self):
        mo = self._make_mo()
        move = mo.move_raw_ids
        move.state = "done"
        with self.assertRaises(UserError):
            move._apply_alternative_product(self.alt_high)

    # ------------------------------------------------------------------
    # Orderpoint wizard (information only)
    # ------------------------------------------------------------------
    def test_orderpoint_wizard(self):
        self._set_stock(self.alt_high, 10.0)
        orderpoint = self.env["stock.warehouse.orderpoint"].create({
            "product_id": self.main.id,
            "location_id": self.stock.id,
            "qty_to_order": 2.0,
        })
        action = orderpoint.action_view_alternatives()
        wizard = self.env["mrp.alternative.selector"].browse(action["res_id"])
        self.assertEqual(wizard.mode, "orderpoint")
        self.assertEqual(len(wizard.line_ids), 3)
        suggested = wizard.line_ids.filtered("is_suggested")
        self.assertEqual(suggested.alternative_product_id, self.alt_high)

    def test_orderpoint_wizard_shows_mo_in_use(self):
        """After an alternative is applied on an MO, the replenishment
        popup links the need to that MO and marks the product in use."""
        self._set_stock(self.alt_high, 10.0)
        mo = self._make_mo()
        self._open_wizard(mo).action_apply()
        orderpoint = self.env["stock.warehouse.orderpoint"].create({
            "product_id": self.main.id,
            "location_id": self.stock.id,
            "qty_to_order": 2.0,
        })
        action = orderpoint.action_view_alternatives()
        wizard = self.env["mrp.alternative.selector"].browse(
            action["res_id"])
        self.assertTrue(wizard.has_move_lines)
        move_line = wizard.move_line_ids.filtered(
            lambda l: l.production_id == mo)
        self.assertEqual(len(move_line), 1)
        self.assertEqual(move_line.move_product_id, self.alt_high)
        self.assertTrue(move_line.is_alternative)
        self.assertEqual(move_line.demand_qty, 2.0)
        in_use = wizard.line_ids.filtered("is_current")
        self.assertEqual(in_use.alternative_product_id, self.alt_high)

    # ------------------------------------------------------------------
    # BOM alternative_mode parameter
    # ------------------------------------------------------------------
    def test_mode_auto_applies_without_popup(self):
        """alternative_mode='auto': on confirm, the covering alternative
        is applied directly, no wizard action is returned."""
        self.bom.alternative_mode = "auto"
        self._set_stock(self.alt_low, 1.0)
        self._set_stock(self.alt_high, 10.0)
        mo = self._make_mo()  # action_confirm() runs inside
        move = mo.move_raw_ids
        # C Jant (priority 20) covers, B (priority 10) does not → C applied
        self.assertEqual(move.product_id, self.alt_high)
        self.assertTrue(move.is_alternative_component)
        self.assertEqual(move.original_product_id, self.main)

    def test_mode_auto_keeps_main_when_nothing_covers(self):
        """alternative_mode='auto': no covering alternative → move keeps
        the main component."""
        self.bom.alternative_mode = "auto"
        self._set_stock(self.alt_low, 1.0)
        mo = self._make_mo()
        move = mo.move_raw_ids
        self.assertEqual(move.product_id, self.main)
        self.assertFalse(move.is_alternative_component)

    def test_mode_manual_does_not_open_popup(self):
        """alternative_mode='manual': confirm returns the standard result,
        no wizard; the user selects via the button."""
        self.bom.alternative_mode = "manual"
        self._set_stock(self.alt_high, 10.0)
        mo = self.env["mrp.production"].create({
            "product_id": self.finished.id,
            "bom_id": self.bom.id,
            "product_qty": 1.0,
            "location_src_id": self.stock.id,
        })
        result = mo.action_confirm()
        # must not be a wizard action
        self.assertNotIsInstance(result, dict)
        self.assertEqual(mo.move_raw_ids.product_id, self.main)
