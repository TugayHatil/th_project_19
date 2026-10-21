# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPurchaseNeedPlan(TransactionCase):
    """BRD §11 acceptance tests for the Material Need Planning screen."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Need = cls.env["mrp.purchase.need"]
        cls.Partner = cls.env["res.partner"]
        cls.supplier = cls.Partner.create({"name": "Need Plan Supplier"})

        cls.vida = cls._make_product(cls, "Vida", proc_days=2, lead=5)
        cls.ayak = cls._make_product(cls, "Masa Ayagi", proc_days=3, lead=5)
        cls.table = cls._make_product(cls, "Masa", purchase=False)

    # -- helpers ---------------------------------------------------------

    def _make_product(self, name, proc_days=None, lead=0, purchase=True):
        tmpl = self.env["product.template"].create({
            "name": name,
            "is_storable": True,
            "purchase_ok": purchase,
            "x_purchase_process_days": proc_days or False,
        })
        if lead:
            self.env["product.supplierinfo"].create({
                "partner_id": self.supplier.id,
                "product_tmpl_id": tmpl.id,
                "delay": lead,
                "min_qty": 1.0,
            })
        return tmpl.product_variant_id

    def _make_mo(self, component, qty, need_date):
        """One confirmed MO that consumes `qty` of `component` on `need_date`."""
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": self.table.product_tmpl_id.id,
            "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {
                "product_id": component.id,
                "product_qty": qty,
            })],
        })
        mo = self.env["mrp.production"].create({
            "product_id": self.table.id,
            "product_qty": 1.0,
            "bom_id": bom.id,
            "date_start": need_date,
        })
        mo.action_confirm()
        move = mo.move_raw_ids.filtered(
            lambda m: m.product_id == component and m.state != "cancel")[:1]
        # pin the scheduled consumption date for a deterministic plan
        move.date = fields.Datetime.to_datetime(need_date)
        return move

    def _set_default_days(self, days):
        Param = self.env["ir.config_parameter"].sudo()
        key = "mrp_purchase_need_plan.default_process_days"
        if days is None:
            Param.search([("key", "=", key)]).unlink()
        else:
            Param.set_param(key, str(days))

    def _lines(self, product, **kw):
        return self.Need.get_need_lines(product.id, **kw)["lines"]

    def _groups(self, **kw):
        return self.Need.get_need_groups(**kw)["groups"]

    def _group(self, product, **kw):
        for group in self._groups(**kw):
            if group["product_id"] == product.id:
                return group
        return None

    def tearDown(self):
        self._set_default_days(None)
        super().tearDown()

    # -- BRD §11 tests ----------------------------------------------------

    def test_01_product_grouping(self):
        """Two products / five need rows -> two groups, five lines (Test 1)."""
        d = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 400, d)
        self._make_mo(self.vida, 200, d + timedelta(days=1))
        self._make_mo(self.ayak, 100, d)
        self._make_mo(self.ayak, 200, d + timedelta(days=1))
        self._make_mo(self.ayak, 400, d + timedelta(days=2))

        vida_group = self._group(self.vida)
        ayak_group = self._group(self.ayak)
        self.assertTrue(vida_group and ayak_group)
        self.assertEqual(vida_group["need_count"], 2)
        self.assertEqual(ayak_group["need_count"], 3)
        self.assertEqual(len(self._lines(self.vida)), 2)
        self.assertEqual(len(self._lines(self.ayak)), 3)

    def test_02_product_days_priority(self):
        """Product card value beats the global default (Test 2)."""
        self._set_default_days(5)
        need = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 10, need)  # proc_days = 2 on the card

        line = self._lines(self.vida)[0]
        # approve_by = need - 5 lead, start = approve_by - 2 card days
        self.assertEqual(
            fields.Date.to_date(line["purchase_start"]),
            need - timedelta(days=7),
        )

    def test_03_default_days_fallback(self):
        """Empty product card -> global default is used (Test 3)."""
        self._set_default_days(3)
        self.vida.product_tmpl_id.x_purchase_process_days = False
        need = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 10, need)

        line = self._lines(self.vida)[0]
        self.assertEqual(
            fields.Date.to_date(line["purchase_start"]),
            need - timedelta(days=8),  # 5 lead + 3 default days
        )
        self.assertFalse(line["missing_lead_config"])

    def test_03b_missing_config_flag(self):
        """No card value and no default -> warning flag, no silent zero."""
        need = fields.Date.today() + timedelta(days=30)
        self.vida.product_tmpl_id.x_purchase_process_days = False
        self._make_mo(self.vida, 10, need)
        line = self._lines(self.vida)[0]
        self.assertTrue(line["missing_lead_config"])

    def test_04_date_calculation(self):
        """need - lead = approve_by; approve_by - proc days = start (Test 4)."""
        need = fields.Date(2026, 10, 29)
        self._make_mo(self.ayak, 10, need)  # lead 5, proc 3

        line = self._lines(self.ayak)[0]
        self.assertEqual(
            fields.Date.to_date(line["approve_by"]),
            fields.Date(2026, 10, 24))
        self.assertEqual(
            fields.Date.to_date(line["purchase_start"]),
            fields.Date(2026, 10, 21))

    def test_05_forecast_running_balance(self):
        """0 stock, needs 400 then 200 -> forecast -400 then -600 (Test 5)."""
        d = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 400, d)
        self._make_mo(self.vida, 200, d + timedelta(days=1))

        lines = self._lines(self.vida)
        self.assertAlmostEqual(lines[0]["forecast"], -400.0)
        self.assertAlmostEqual(lines[1]["forecast"], -600.0)
        self.assertAlmostEqual(lines[0]["uncovered_qty"], 400.0)
        self.assertAlmostEqual(lines[1]["uncovered_qty"], 200.0)

    def test_06_merged_purchase_request(self):
        """Vida 400+200 and Ayak 100+200+400 -> one request, 2 lines
        with 600 and 700 (Test 6 + §8 scenario)."""
        d = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 400, d)
        self._make_mo(self.vida, 200, d + timedelta(days=1))
        self._make_mo(self.ayak, 100, d)
        self._make_mo(self.ayak, 200, d + timedelta(days=1))
        self._make_mo(self.ayak, 400, d + timedelta(days=2))

        res = self.Need.create_purchase_request(
            [self.vida.id, self.ayak.id])
        self.assertEqual(len(res["requests"]), 1)
        request = self.env["purchase.request"].browse(res["requests"][0]["id"])
        self.assertEqual(len(request.line_ids), 2)
        qty = {ln.product_id: ln.product_qty for ln in request.line_ids}
        self.assertAlmostEqual(qty[self.vida], 600.0)
        self.assertAlmostEqual(qty[self.ayak], 700.0)
        # BRD §7.3 — every source move stays linked to its request line
        vida_line = request.line_ids.filtered(
            lambda ln: ln.product_id == self.vida)
        self.assertEqual(len(vida_line.need_move_ids), 2)
        need_dates = {
            fields.Date.to_date(m.date) for m in vida_line.need_move_ids}
        self.assertEqual(len(need_dates), 2)
        # earliest need drives the line's required date
        self.assertEqual(vida_line.date_required, min(need_dates))

    def test_06b_line_level_selection(self):
        """move_ids selects individual need rows: only the picked line's
        uncovered quantity flows into the request."""
        d = fields.Date.today() + timedelta(days=30)
        m1 = self._make_mo(self.vida, 400, d)
        m2 = self._make_mo(self.vida, 200, d + timedelta(days=1))

        res = self.Need.create_purchase_request(move_ids=[m2.id])
        request = self.env["purchase.request"].browse(res["requests"][0]["id"])
        self.assertEqual(len(request.line_ids), 1)
        self.assertAlmostEqual(request.line_ids.product_qty, 200.0)
        self.assertEqual(request.line_ids.need_move_ids, m2)

        # the unselected line is still fully requestable
        res2 = self.Need.create_purchase_request(move_ids=[m1.id])
        req2 = self.env["purchase.request"].browse(res2["requests"][0]["id"])
        self.assertAlmostEqual(req2.line_ids.product_qty, 400.0)

    def test_07_stock_change_rechecked(self):
        """New stock before requesting -> covered qty not re-requested
        (Test 7)."""
        d = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 400, d)
        # stock arrives after the screen was opened
        self.env["stock.quant"]._update_available_quantity(
            self.vida, self.env.ref("stock.stock_location_stock"), 250)

        res = self.Need.create_purchase_request([self.vida.id])
        request = self.env["purchase.request"].browse(res["requests"][0]["id"])
        self.assertAlmostEqual(request.line_ids.product_qty, 150.0)

    def test_09_duplicate_request_blocked(self):
        """Requesting the same needs twice -> UserError (Test 9)."""
        d = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 400, d)
        self.Need.create_purchase_request([self.vida.id])
        with self.assertRaises(UserError):
            self.Need.create_purchase_request([self.vida.id])

    def test_10_open_po_counts_as_supply(self):
        """An open PO line reaching the scope in time covers the need
        (Test 8)."""
        d = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 400, d)
        wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        po = self.env["purchase.order"].create({
            "partner_id": self.supplier.id,
            "order_line": [(0, 0, {
                "product_id": self.vida.id,
                "product_qty": 300,
                "price_unit": 1.0,
                "product_uom_id": self.vida.uom_id.id,
                "date_planned": fields.Datetime.to_datetime(
                    d - timedelta(days=5)),
            })],
        })
        po.button_confirm()
        move = po.picking_ids.move_ids.filtered(
            lambda m: m.product_id == self.vida)[:1]
        move.date = fields.Datetime.to_datetime(d - timedelta(days=5))
        self.assertIn(move.location_dest_id.id,
                      self.Need._get_scope_locations(wh.id).ids)

        line = self._lines(self.vida)[0]
        self.assertAlmostEqual(line["forecast"], -100.0)
        self.assertAlmostEqual(line["uncovered_qty"], 100.0)

    def _confirm_po(self, product, qty, delivery_date):
        po = self.env["purchase.order"].create({
            "partner_id": self.supplier.id,
            "order_line": [(0, 0, {
                "product_id": product.id,
                "product_qty": qty,
                "price_unit": 1.0,
                "product_uom_id": product.uom_id.id,
                "date_planned": fields.Datetime.to_datetime(delivery_date),
            })],
        })
        po.button_confirm()
        move = po.picking_ids.move_ids.filtered(
            lambda m: m.product_id == product)[:1]
        move.date = fields.Datetime.to_datetime(delivery_date)
        return po, move

    def test_11_pull_forward_suggestion(self):
        """Late open PO -> pull-forward suggestion. The suggestion is
        informational only: until the order is actually rescheduled the
        needs stay uncovered at their own dates.

        Stock 0, needs 400 @D and 200 @D+1, open PO 100 @D+10:
        suggestion = D (10 days early, covers 100 of the first need),
        but uncovered stays 400 + 200 = 600 and a request asks 600.
        """
        d = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 400, d)
        self._make_mo(self.vida, 200, d + timedelta(days=1))
        po, move = self._confirm_po(self.vida, 100, d + timedelta(days=10))

        res = self.Need.get_need_lines(self.vida.id)
        lines, suggestions = res["lines"], res["suggestions"]

        self.assertEqual(len(suggestions), 1)
        sug = suggestions[0]
        self.assertEqual(sug["move_id"], move.id)
        self.assertEqual(sug["order"], po.name)
        self.assertEqual(
            fields.Date.to_date(sug["suggested_date"]), d)
        self.assertEqual(sug["days"], 10)
        self.assertAlmostEqual(sug["cover_qty"], 100.0)
        self.assertAlmostEqual(sug["covers"][0]["qty"], 100.0)
        self.assertEqual(
            fields.Date.to_date(sug["covers"][0]["need_date"]), d)

        # planning still follows the real Nov-8 delivery date
        self.assertAlmostEqual(lines[0]["uncovered_qty"], 400.0)
        self.assertAlmostEqual(lines[0]["pull_covered"], 100.0)
        self.assertAlmostEqual(lines[1]["uncovered_qty"], 200.0)
        self.assertAlmostEqual(
            res["group"]["total_uncovered"], 600.0)

        res2 = self.Need.create_purchase_request([self.vida.id])
        request = self.env["purchase.request"].browse(res2["requests"][0]["id"])
        self.assertAlmostEqual(request.line_ids.product_qty, 600.0)

    def test_12_customer_delivery_as_need(self):
        """A confirmed outgoing picking shows up as its own need row,
        dated by the delivery deadline, with the risk flag set when the
        computed purchase start is already in the past."""
        d = fields.Date.today() + timedelta(days=5)
        wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        customer_loc = self.env.ref("stock.stock_location_customers")
        picking = self.env["stock.picking"].create({
            "picking_type_id": wh.out_type_id.id,
            "location_id": wh.lot_stock_id.id,
            "location_dest_id": customer_loc.id,
        })
        move = self.env["stock.move"].create({
            "product_id": self.vida.id,
            "product_uom_qty": 30,
            "product_uom": self.vida.uom_id.id,
            "picking_id": picking.id,
            "location_id": wh.lot_stock_id.id,
            "location_dest_id": customer_loc.id,
        })
        picking.action_confirm()
        move.date_deadline = fields.Datetime.to_datetime(d)

        lines = self._lines(self.vida)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(fields.Date.to_date(line["need_date"]), d)
        self.assertAlmostEqual(line["need_qty"], 30.0)
        self.assertAlmostEqual(line["uncovered_qty"], 30.0)
        # lead 5 + proc 2 -> purchase start is already past -> late risk
        self.assertTrue(line["is_late"])

    def test_11b_no_suggestion_when_po_on_time(self):
        """PO arriving before the need covers it directly — no pull
        suggestion is emitted."""
        d = fields.Date.today() + timedelta(days=30)
        self._make_mo(self.vida, 400, d)
        self._confirm_po(self.vida, 100, d - timedelta(days=5))

        res = self.Need.get_need_lines(self.vida.id)
        self.assertFalse(res["suggestions"])
        self.assertAlmostEqual(res["lines"][0]["uncovered_qty"], 300.0)
