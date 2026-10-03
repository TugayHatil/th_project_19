# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import UserError
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
        data = Cap.get_capacity_grid(workcenter_ids=[wc.id])
        self.assertEqual(len(data["periods"]), 12)
        row = next(r for r in data["rows"] if r["workcenter_id"] == wc.id)
        self.assertEqual(len(row["cells"]), 12)
        cell = row["cells"][0]
        # capacity comes from the workcenter calendar, not constants
        self.assertGreater(cell["cap_h"], 0)
        # 2 units x 60 min operation = 2h of planned load in the first month
        self.assertGreater(cell["plan_h"], 0)
        # diff = capacity - (planned + required) (BRD §12)
        self.assertAlmostEqual(cell["rem_h"], cell["cap_h"] - cell["plan_h"])
        self.assertAlmostEqual(cell["tot_h"], cell["plan_h"] + cell["req_h"])
        self.assertAlmostEqual(cell["diff_h"], cell["cap_h"] - cell["tot_h"])
        # overload flag and filter
        self.assertFalse(row["overload"])
        over = Cap.get_capacity_grid(overload_only=True)
        self.assertTrue(all(r["overload"] for r in over["rows"]))

    def test_required_production_via_bom(self):
        # unmet demand (no stock, no MO) on a flagged product must turn into
        # required-production hours on its BOM operation's workcenter
        Line = self.Line
        Cap = self.env["mrp.ltp.capacity"]
        wc = self.env["mrp.workcenter"].create({"name": "LTP Line Y"})
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": self.p_flagged.product_tmpl_id.id,
            "product_qty": 1,
            "operation_ids": [Command.create({
                "name": "Assemble", "workcenter_id": wc.id, "time_cycle": 30,
            })],
        })
        periods = Line._periods(*Line._current_period())
        py, pm = periods[0]
        # confirmed sales demand (no stock, no MO) → required production
        partner = self.env["res.partner"].create({"name": "LTP Customer"})
        so = self.env["sale.order"].create({
            "partner_id": partner.id,
            "commitment_date": f"{py}-{pm:02d}-15 12:00:00",
            "order_line": [Command.create({
                "product_id": self.p_flagged.id,
                "product_uom_qty": 8,
            })],
        })
        so.action_confirm()
        req = Cap._required_load_map(
            periods, self.env["mrp.workcenter"].browse(wc.id))
        key = (wc.id, Line._abs_month(py, pm))
        # 8 units x 30 min = 4 h on the operation's workcenter
        self.assertAlmostEqual(req.get(key, 0.0), 4.0)

    def test_required_is_demand_minus_existing_production(self):
        # 100 ordered, 10 covered by an open MO → required is 90, and the
        # total workload equals demand (10 planned + 90 required = 100)
        Line = self.Line
        Cap = self.env["mrp.ltp.capacity"]
        periods = Line._periods(*Line._current_period())
        py, pm = periods[0]
        partner = self.env["res.partner"].create({"name": "LTP Customer 2"})
        so = self.env["sale.order"].create({
            "partner_id": partner.id,
            "commitment_date": f"{py}-{pm:02d}-15 12:00:00",
            "order_line": [Command.create({
                "product_id": self.p_flagged.id,
                "product_uom_qty": 100,
            })],
        })
        so.action_confirm()
        self.env["mrp.production"].create({
            "product_id": self.p_flagged.id,
            "product_qty": 10,
            "product_uom_id": self.p_flagged.uom_id.id,
            "date_start": f"{py}-{pm:02d}-20 08:00:00",
        })
        req_map = Cap._required_qty_map(periods)
        key = (self.p_flagged.id, Line._abs_month(py, pm))
        self.assertAlmostEqual(req_map.get(key, 0.0), 90.0)

    def test_capacity_factor(self):
        # BRD §5/§14: revised capacity = standard x factor; only the
        # selected workcenter+month changes; 1.0 removes the override
        Cap = self.env["mrp.ltp.capacity"]
        periods = self.Line._periods(*self.Line._current_period())
        sy, sm = periods[0]
        wc = self.env["mrp.workcenter"].create({"name": "LTP Line F"})
        base = Cap.get_capacity_grid(workcenter_ids=[wc.id])
        cell0 = base["rows"][0]["cells"][0]
        std_cap = cell0["cap_h"]
        self.assertEqual(cell0["factor"], 1.0)

        res = Cap.set_capacity_factor(
            wc.id, sy, sm, 1.2, start_year=sy, start_month=sm)
        cell = res["row"]["cells"][0]
        self.assertAlmostEqual(cell["cap_h"], std_cap * 1.2)
        self.assertAlmostEqual(cell["rem_h"], cell["cap_h"] - cell["plan_h"])
        self.assertAlmostEqual(cell["diff_h"], cell["cap_h"] - cell["tot_h"])
        # the following month is untouched (BRD §6)
        self.assertEqual(res["row"]["cells"][1]["factor"], 1.0)
        self.assertAlmostEqual(res["row"]["cells"][1]["cap_h"],
                               base["rows"][0]["cells"][1]["cap_h"])

        # zero / negative / text are rejected (BRD §13)
        for bad in (0, -2, "abc"):
            with self.assertRaises(UserError):
                Cap.set_capacity_factor(wc.id, sy, sm, bad)

        # resetting to 1.00 removes the override (BRD §14)
        res = Cap.set_capacity_factor(
            wc.id, sy, sm, 1.0, start_year=sy, start_month=sm)
        self.assertAlmostEqual(res["row"]["cells"][0]["cap_h"], std_cap)
        self.assertFalse(self.env["mrp.ltp.capacity.factor"].search_count([
            ("workcenter_id", "=", wc.id),
        ]))

    def test_revision_confirm_baseline_and_compare(self):
        # BRD §5-§19: confirm freezes a baseline; live order changes must
        # not touch it; every confirm creates a NEW revision; history and
        # comparison read the stored snapshots.
        Line = self.Line
        periods = Line._periods(*Line._current_period())
        py, pm = periods[0]

        res1 = Line.confirm_plan()
        rev1 = res1["revision"]
        self.assertTrue(rev1["name"])
        base = Line.get_baseline()
        self.assertEqual(base["revision"]["id"], rev1["id"])
        key = "%s:%s" % (self.p_flagged.id, rev1["period_start"])
        self.assertEqual(base["lines"][key]["os"], 0)

        # a new order arrives AFTER the confirm → live moves, baseline stays
        partner = self.env["res.partner"].create({"name": "LTP Rev Customer"})
        so = self.env["sale.order"].create({
            "partner_id": partner.id,
            "commitment_date": f"{py}-{pm:02d}-15 12:00:00",
            "order_line": [Command.create({
                "product_id": self.p_flagged.id,
                "product_uom_qty": 120,
            })],
        })
        so.action_confirm()
        base = Line.get_baseline()
        self.assertEqual(base["lines"][key]["os"], 0)  # frozen baseline
        grid = Line.get_planning_grid(limit=200)
        row = next(r for r in grid["rows"]
                   if r["product_id"] == self.p_flagged.id)
        self.assertEqual(row["cells"][0]["os"], 120)   # live order

        # second confirm → a NEW revision, old one preserved (§6/§10)
        res2 = Line.confirm_plan()
        rev2 = res2["revision"]
        self.assertNotEqual(rev1["id"], rev2["id"])
        base = Line.get_baseline()
        self.assertEqual(base["revision"]["id"], rev2["id"])
        self.assertEqual(base["lines"][key]["os"], 120)  # rebaselined (§19)
        revs = Line.get_revision_list()
        self.assertEqual([r["id"] for r in revs][:2], [rev2["id"], rev1["id"]])

        # history view shows the stored snapshot (§14)
        data = Line.get_revision_data(rev1["id"])
        r1 = next(r for r in data["rows"]
                  if r["product_id"] == self.p_flagged.id)
        self.assertEqual(r1["cells"][0]["os"], 0)

        # rev1 vs live comparison (§15): delta = live - baseline
        cmp_ = Line.get_compare_data(rev1["id"], False)
        crow = next(r for r in cmp_["rows"]
                    if r["product_id"] == self.p_flagged.id)
        self.assertEqual(crow["cells"][0]["a"], 0)
        self.assertEqual(crow["cells"][0]["b"], 120)
        self.assertEqual(crow["cells"][0]["delta"], 120)
