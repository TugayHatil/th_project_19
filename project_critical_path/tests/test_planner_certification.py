# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestPlannerCertification(TransactionCase):
    """Planner v1 certification suite (docs/planner-certification-v1.md).

    Covers the scheduling/persistence behaviours certified stable by the
    MCP browser regression: parallel-predecessor max() bounds, all four
    dependency relation types, FS lag across a day boundary, the planner
    payload contract and the Inspector day-scale save path.
    """

    def _task(self, project, name, start, stop, **values):
        return self.env["project.task"].create({
            "name": name, "project_id": project.id,
            "date_assign": start, "date_deadline": stop, **values,
        })

    def test_parallel_predecessor_uses_latest_bound(self):
        """A successor with two predecessors waits for the LATEST bound —
        moving the early predecessor alone must not shift it."""
        project = self.env["project.project"].create({"name": "Parallel bound"})
        early = self._task(project, "Early", "2026-09-14 09:00:00", "2026-09-15 09:00:00")
        late = self._task(project, "Late", "2026-09-14 09:00:00", "2026-09-15 18:00:00")
        succ = self._task(project, "Succ", "2026-09-15 18:00:00", "2026-09-16 09:00:00",
                          depend_on_ids=[(4, early.id), (4, late.id)])

        # Moving the early predecessor inside the slack of the late one
        # must not move the successor.
        early.write({"date_deadline": "2026-09-15 14:00:00"})
        self.assertEqual(str(succ.date_assign)[:16], "2026-09-15 18:00")

        # Pushing the late predecessor past the bound cascades exactly.
        late.write({"date_deadline": "2026-09-16 06:00:00"})
        self.assertEqual(str(succ.date_assign)[:16], "2026-09-16 06:00")
        self.assertEqual(str(succ.date_deadline)[:16], "2026-09-16 21:00")

        # Pulling the late predecessor back earlier relaxes nothing —
        # bounds only ever push forward.
        late.write({"date_deadline": "2026-09-15 18:00:00"})
        self.assertEqual(str(succ.date_assign)[:16], "2026-09-16 06:00")

    def test_relation_type_bounds(self):
        """SS, FF and SF edges constrain the successor on their own field —
        the shift lands exactly on the bound, keeping the wall span."""
        project = self.env["project.project"].create({"name": "Relation types"})
        pred = self._task(project, "P", "2026-09-14 09:00:00", "2026-09-15 18:00:00")

        # SS +24h: successor starts no earlier than pred.start + 24h.
        ss = self._task(project, "SS", "2026-09-14 09:00:00", "2026-09-14 18:00:00",
                        depend_on_ids=[(4, pred.id)])
        ss.update_planner_dependency(pred.id, "ss", 24, "hours")
        self.assertEqual(str(ss.date_assign)[:16], "2026-09-15 09:00")
        self.assertEqual(str(ss.date_deadline)[:16], "2026-09-15 18:00")

        # FF +10h: successor finishes no earlier than pred.finish + 10h —
        # the start is derived from the bound minus the 9h span.
        ff = self._task(project, "FF", "2026-09-15 18:00:00", "2026-09-16 03:00:00",
                        depend_on_ids=[(4, pred.id)])
        ff.update_planner_dependency(pred.id, "ff", 10, "hours")
        self.assertEqual(str(ff.date_deadline)[:16], "2026-09-16 04:00")
        self.assertEqual(str(ff.date_assign)[:16], "2026-09-15 19:00")

        # SF +20h: successor finishes no earlier than pred.start + 20h.
        sf = self._task(project, "SF", "2026-09-14 09:00:00", "2026-09-14 12:00:00",
                        depend_on_ids=[(4, pred.id)])
        sf.update_planner_dependency(pred.id, "sf", 20, "hours")
        self.assertEqual(str(sf.date_deadline)[:16], "2026-09-15 05:00")
        self.assertEqual(str(sf.date_assign)[:16], "2026-09-15 02:00")

    def test_fs_lag_spans_day_boundary(self):
        """FS +10h: a predecessor finishing at 19:00 pushes the successor
        to 05:00 the next day — hour precision survives midnight."""
        project = self.env["project.project"].create({"name": "Overnight lag"})
        pred = self._task(project, "P", "2026-09-15 10:00:00", "2026-09-15 19:00:00")
        succ = self._task(project, "S", "2026-09-15 19:00:00", "2026-09-16 04:00:00",
                          depend_on_ids=[(4, pred.id)])
        succ.update_planner_dependency(pred.id, "fs", 10, "hours")
        self.assertEqual(str(succ.date_assign)[:16], "2026-09-16 05:00")
        self.assertEqual(str(succ.date_deadline)[:16], "2026-09-16 14:00")

    def test_planner_payload_serializes_schedule(self):
        """get_planner_data is the planner's contract: WBS order, localized
        dt fields, dependency edges with type/lag, critical flags and
        baseline snapshot coordinates."""
        project = self.env["project.project"].create({"name": "Payload"})
        first = self._task(project, "A", "2026-09-15 09:00:00", "2026-09-15 18:00:00",
                           allocated_hours=8)
        second = self._task(project, "B", "2026-09-15 18:00:00", "2026-09-16 09:00:00",
                            allocated_hours=8, depend_on_ids=[(4, first.id)])
        second.update_planner_dependency(first.id, "fs", 10, "hours")

        data = project.get_planner_data()
        rows = {row["name"]: row for row in data["tasks"]}
        self.assertEqual(rows["A"]["wbs_code"], "1")
        self.assertEqual(rows["B"]["wbs_code"], "2")
        # FS+10h pushed B: A.finish 18:00 + 10h = next-day 04:00 start,
        # keeping its 15h span.
        self.assertEqual(rows["A"]["dt_start"][:16], "2026-09-15 09:00")
        self.assertEqual(rows["B"]["dt_start"][:16], "2026-09-16 04:00")
        self.assertEqual(rows["B"]["dt_stop"][:16], "2026-09-16 19:00")
        self.assertEqual(rows["B"]["depend_on_ids"], [first.id])
        edge = rows["B"]["dependencies"][0]
        self.assertEqual(edge["type"], "fs")
        self.assertEqual(edge["lag_hours"], 10.0)
        self.assertIn("is_critical", rows["A"])
        self.assertIn("critical_slack", rows["A"])

        project.action_create_critical_path_baseline()
        data = project.get_planner_data()
        rows = {row["name"]: row for row in data["tasks"]}
        self.assertTrue(rows["A"]["baseline_name"])
        self.assertEqual(rows["A"]["baseline_start"], "2026-09-15")
        self.assertEqual(rows["A"]["baseline_stop"], "2026-09-15")

    def test_inspector_day_path_save(self):
        """Inspector day inputs persist through date_start/date_stop and
        keep allocated_hours synced to the inclusive day span."""
        project = self.env["project.project"].create({"name": "Inspector days"})
        task = self._task(project, "T", "2026-09-15 09:00:00", "2026-09-15 18:00:00",
                          allocated_hours=8)
        task.update_planner_task({
            "date_start": "2026-09-20", "date_stop": "2026-09-22",
            "duration_days": 3,
        })
        self.assertTrue(task.date_assign)
        self.assertTrue(task.date_deadline)
        self.assertEqual(str(task.date_assign)[:10], "2026-09-20")
        self.assertEqual(str(task.date_deadline)[:10], "2026-09-22")
        # A day-span matching duration_days leaves allocated_hours alone;
        # a different duration syncs it to days * hours-per-day.
        self.assertEqual(task.allocated_hours, 8)
        task.update_planner_task({
            "date_start": "2026-09-20", "date_stop": "2026-09-22",
            "duration_days": 5,
        })
        from odoo.addons.project_critical_path.models.project_planner import (
            _planner_hours_per_day,
        )
        self.assertAlmostEqual(task.allocated_hours, 5 * _planner_hours_per_day(task), places=2)
