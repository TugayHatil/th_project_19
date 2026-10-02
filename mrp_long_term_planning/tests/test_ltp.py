# -*- coding: utf-8 -*-
from odoo import fields
from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestLongTermPlanning(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Line = cls.env["mrp.ltp.line"]
        cls.p_flagged = cls.env["product.product"].create({
            "name": "LTP Product A",
            "x_long_term_production_planning": True,
        })
        cls.p_plain = cls.env["product.product"].create({
            "name": "LTP Product B",
        })

    def test_rolling_periods(self):
        # the window always starts at the current server month (BRD rev §2)
        year, month = self.Line._current_period()
        periods = self.Line._periods(year, month)
        self.assertEqual(len(periods), 12)
        self.assertEqual(periods[0], (year, month))
        end_idx = year * 12 + month - 1 + 11
        self.assertEqual(periods[-1], (end_idx // 12, end_idx % 12 + 1))
        # year boundary: Oct 2026 + 3 → Jan 2027
        self.assertEqual(self.Line._periods(2026, 10, 4),
                         [(2026, 10), (2026, 11), (2026, 12), (2027, 1)])

    def test_build_cells_formulas(self):
        # BRD example: OS=150, SM=50, GM=30 → IM=70; PM=100 → DS=30
        periods = self.Line._periods(2026, 10)
        oct_key = (999, self.Line._abs_month(2026, 10))
        nov_key = (999, self.Line._abs_month(2026, 11))
        cells = self.Line._build_cells(
            periods, 999, 50, {oct_key: 150}, {oct_key: 30}, {oct_key: 100})
        self.assertEqual(cells[0]["im"], 70)
        self.assertEqual(cells[0]["ds"], 30)
        # rolling: DS rolls into next month's SM (BRD §9)
        self.assertEqual(cells[1]["sm"], 30)
        # cells carry the real year/month pair (BRD rev §8)
        self.assertEqual((cells[3]["year"], cells[3]["month"]), (2027, 1))
        # a value keyed to a different year/month must not leak into a cell
        self.assertEqual(cells[1]["os"], 0)
        cells = self.Line._build_cells(
            periods, 999, 50, {nov_key: 20}, {}, {})
        self.assertEqual(cells[1]["os"], 20)
        self.assertEqual(cells[0]["os"], 0)

    def test_im_never_negative(self):
        periods = self.Line._periods(2027, 1)
        key = (1, self.Line._abs_month(2027, 1))
        cells = self.Line._build_cells(periods, 1, 200, {key: 100}, {}, {})
        self.assertEqual(cells[0]["im"], 0)
        self.assertEqual(cells[0]["ds"], 100)

    def test_incoming_draft_production_counts_as_gm(self):
        # a draft (unconfirmed) MO is still planned supply → GM (BRD §8)
        periods = self.Line._periods(*self.Line._current_period())
        sy, sm = periods[0]
        self.env["mrp.production"].create({
            "product_id": self.p_flagged.id,
            "product_qty": 10,
            "product_uom_id": self.p_flagged.uom_id.id,
            "date_start": f"{sy}-{sm:02d}-15 08:00:00",
        })
        gm_map = self.Line._incoming_qty_map([self.p_flagged.id], periods, False)
        key = (self.p_flagged.id, self.Line._abs_month(sy, sm))
        self.assertEqual(gm_map.get(key), 10)

    def test_grid_filters_flagged_products(self):
        data = self.Line.get_planning_grid(limit=200)
        ids = {row["product_id"] for row in data["rows"]}
        self.assertIn(self.p_flagged.id, ids)
        self.assertNotIn(self.p_plain.id, ids)
        self.assertEqual(len(data["periods"]), 12)

    def test_planned_qty_upsert_and_window(self):
        year, month = self.Line._current_period()
        py, pm = self.Line._periods(year, month)[2]
        res = self.Line.set_planned_qty(self.p_flagged.id, py, pm, False, 100)
        self.assertEqual(res["row"]["cells"][2]["pm"], 100)
        self.assertEqual(
            (res["row"]["cells"][2]["year"], res["row"]["cells"][2]["month"]),
            (py, pm))
        # second write updates the same line instead of duplicating it
        res = self.Line.set_planned_qty(self.p_flagged.id, py, pm, False, 50)
        self.assertEqual(res["row"]["cells"][2]["pm"], 50)
        self.assertEqual(self.Line.search_count([
            ("product_id", "=", self.p_flagged.id),
            ("year", "=", py),
            ("month", "=", pm),
        ]), 1)
        # a PM outside the window is preserved but not shown (BRD rev §9)
        self.Line.set_planned_qty(self.p_flagged.id, year + 5, 1, False, 77)
        self.assertTrue(all(cell["pm"] != 77 for cell in res["row"]["cells"]))
        self.assertEqual(self.Line.search_count([
            ("product_id", "=", self.p_flagged.id),
        ]), 2)

    def test_capacity_grid(self):
        Cap = self.env["mrp.ltp.capacity"]
        periods = self.Line._periods(*self.Line._current_period())
        sy, sm = periods[0]
        wc = self.env["mrp.workcenter"].create({"name": "LTP Line X"})
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": self.p_flagged.product_tmpl_id.id,
            "product_qty": 1,
            "operation_ids": [Command.create({
                "name": "Cut", "workcenter_id": wc.id, "time_cycle": 60,
            })],
        })
        mo = self.env["mrp.production"].create({
            "product_id": self.p_flagged.id,
            "bom_id": bom.id,
            "product_qty": 2,
            "product_uom_id": self.p_flagged.uom_id.id,
            "date_start": f"{sy}-{sm:02d}-15 08:00:00",
        })
        mo.action_confirm()
        data = Cap.get_capacity_grid(workcenter_id=wc.id)
        self.assertEqual(len(data["periods"]), 12)
        row = next(r for r in data["rows"] if r["workcenter_id"] == wc.id)
        self.assertEqual(len(row["cells"]), 12)
        cell = row["cells"][0]
        # capacity comes from the workcenter calendar, not constants
        self.assertGreater(cell["cap_h"], 0)
        # 2 units x 60 min operation = 2h of workload in the first month
        self.assertGreater(cell["load_h"], 0)
        self.assertAlmostEqual(cell["diff_h"], cell["cap_h"] - cell["load_h"])
        # overload flag and filter
        self.assertFalse(row["overload"])
        over = Cap.get_capacity_grid(overload_only=True)
        self.assertTrue(all(r["overload"] for r in over["rows"]))
