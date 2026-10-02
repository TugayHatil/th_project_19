# -*- coding: utf-8 -*-
from odoo import fields
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
