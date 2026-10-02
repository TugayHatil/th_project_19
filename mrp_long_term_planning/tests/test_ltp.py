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
        cls.year = fields.Date.today().year + 1

    def test_build_cells_formulas(self):
        # BRD example: OS=150, SM=50, GM=30 → IM=70; PM=100 → DS=30
        cells = self.Line._build_cells(50, {1: 150}, {1: 30}, {1: 100})
        jan = cells[0]
        self.assertEqual(jan["im"], 70)
        self.assertEqual(jan["ds"], 30)
        # rolling: January DS becomes February SM (BRD §9)
        self.assertEqual(cells[1]["sm"], 30)

    def test_im_never_negative(self):
        cells = self.Line._build_cells(200, {1: 100}, {}, {})
        self.assertEqual(cells[0]["im"], 0)
        self.assertEqual(cells[0]["ds"], 100)

    def test_grid_filters_flagged_products(self):
        data = self.Line.get_planning_grid(self.year, limit=200)
        ids = {row["product_id"] for row in data["rows"]}
        self.assertIn(self.p_flagged.id, ids)
        self.assertNotIn(self.p_plain.id, ids)

    def test_planned_qty_upsert(self):
        res = self.Line.set_planned_qty(self.p_flagged.id, self.year, 3, False, 100)
        self.assertEqual(res["row"]["cells"][2]["pm"], 100)
        # second write updates the same line instead of duplicating it
        res = self.Line.set_planned_qty(self.p_flagged.id, self.year, 3, False, 50)
        self.assertEqual(res["row"]["cells"][2]["pm"], 50)
        self.assertEqual(self.Line.search_count([
            ("product_id", "=", self.p_flagged.id),
            ("year", "=", self.year),
            ("month", "=", 3),
        ]), 1)
