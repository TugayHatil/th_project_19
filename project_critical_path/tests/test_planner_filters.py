# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase


class TestPlannerFilters(TransactionCase):
    """Standard Filters & Group By (BRD) — the Filters dropdown builds a
    project.task domain consumed by ``get_planner_data``. These tests pin
    the domain behaviour, ancestor preservation and the meta block, and
    prove filtering never mutates task data, dependencies or rollups.
    """

    def _task(self, project, name, start="2026-09-15 09:00:00", stop="2026-09-15 18:00:00",
              parent=None, **values):
        vals = {
            "name": name, "project_id": project.id,
            "date_assign": start, "date_deadline": stop,
        }
        if parent:
            vals["parent_id"] = parent.id
        vals.update(values)
        return self.env["project.task"].create(vals)

    def _data(self, project, domain=None):
        return project.get_planner_data(domain=domain)

    def _names(self, data):
        return [task["name"] for task in data["tasks"]]

    # ---- Status / time filters -------------------------------------------

    def test_critical_filter(self):
        project = self.env["project.project"].create({"name": "F"})
        a = self._task(project, "A")
        b = self._task(project, "B")
        a.write({"is_critical": True})
        data = self._data(project, [["is_critical", "=", True]])
        self.assertEqual(self._names(data), ["A"])

    def test_done_not_done_filters(self):
        project = self.env["project.project"].create({"name": "F"})
        done = self._task(project, "Done", state="1_done")
        self._task(project, "Open")
        self.assertEqual(
            self._names(self._data(project, [["state", "=", "1_done"]])),
            ["Done"],
        )
        self.assertEqual(
            self._names(self._data(project, [["state", "!=", "1_done"]])),
            ["Open"],
        )
        self.assertEqual(done.state, "1_done")

    def test_overdue_filter(self):
        project = self.env["project.project"].create({"name": "F"})
        past = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        self._task(project, "Late", start="2020-01-01 09:00:00", stop=past)
        self._task(project, "LateDone", start="2020-01-01 09:00:00", stop=past,
                   state="1_done")
        self._task(project, "Future")
        today = datetime.now().strftime("%Y-%m-%d")
        data = self._data(project, [
            ["date_deadline", "!=", False],
            ["date_deadline", "<", today],
            ["state", "!=", "1_done"],
        ])
        self.assertEqual(self._names(data), ["Late"])

    def test_today_filter(self):
        project = self.env["project.project"].create({"name": "F"})
        now = datetime.now()
        self._task(
            project, "TodayTask",
            start=now.strftime("%Y-%m-%d 00:00:00"),
            stop=now.strftime("%Y-%m-%d 23:00:00"),
        )
        self._task(project, "FarAway", start="2030-01-01 09:00:00", stop="2030-01-02 18:00:00")
        today = now.strftime("%Y-%m-%d")
        data = self._data(project, [
            ["date_assign", "<=", f"{today} 23:59:59"],
            ["date_deadline", ">=", today],
        ])
        self.assertEqual(self._names(data), ["TodayTask"])

    def test_multiple_filters_and(self):
        project = self.env["project.project"].create({"name": "F"})
        a = self._task(project, "A")
        b = self._task(project, "B")
        a.write({"is_critical": True})
        b.write({"is_critical": True, "state": "1_done"})
        data = self._data(project, [
            ["is_critical", "=", True],
            ["state", "!=", "1_done"],
        ])
        self.assertEqual(self._names(data), ["A"])

    # ---- Field filters -----------------------------------------------------

    def test_assignee_filter(self):
        project = self.env["project.project"].create({"name": "F"})
        user = self.env["res.users"].search([], limit=1)
        self._task(project, "Mine", user_ids=[(4, user.id)])
        self._task(project, "Other")
        data = self._data(project, [["user_ids", "in", [user.id]]])
        self.assertEqual(self._names(data), ["Mine"])

    def test_parent_child_of_filter(self):
        project = self.env["project.project"].create({"name": "F"})
        a = self._task(project, "A")
        self._task(project, "A1", parent=a)
        self._task(project, "B")
        data = self._data(project, [["id", "child_of", a.id]])
        self.assertEqual(sorted(self._names(data)), ["A", "A1"])

    def test_date_range_filter(self):
        project = self.env["project.project"].create({"name": "F"})
        self._task(project, "Early", start="2026-01-05 09:00:00", stop="2026-01-05 18:00:00")
        self._task(project, "Late", start="2026-12-05 09:00:00", stop="2026-12-05 18:00:00")
        data = self._data(project, [["date_assign", ">=", "2026-06-01"]])
        self.assertEqual(self._names(data), ["Late"])

    # ---- Ancestor preservation --------------------------------------------

    def test_matched_child_keeps_ancestors(self):
        project = self.env["project.project"].create({"name": "F"})
        a = self._task(project, "A")
        a1 = self._task(project, "A1", parent=a)
        self._task(project, "B")
        data = self._data(project, [["id", "=", a1.id]])
        # Child match pulls its parent in for readability — the relation
        # itself is untouched.
        self.assertEqual(self._names(data), ["A", "A1"])
        self.assertEqual(a1.parent_id, a)

    # ---- Meta block (dropdown option lists) --------------------------------

    def test_meta_block(self):
        project = self.env["project.project"].create({"name": "F"})
        user = self.env["res.users"].search([], limit=1)
        a = self._task(project, "A", user_ids=[(4, user.id)])
        self._task(project, "A1", parent=a)
        data = self._data(project)
        self.assertIn("meta", data)
        self.assertIn(user.id, [u["id"] for u in data["meta"]["users"]])
        self.assertIn(a.id, [p["id"] for p in data["meta"]["parents"]])
        task_a1 = next(t for t in data["tasks"] if t["name"] == "A1")
        self.assertEqual(task_a1["user_names"], [])
        task_a = next(t for t in data["tasks"] if t["name"] == "A")
        self.assertEqual(task_a["user_ids"], [user.id])

    # ---- Filters never modify data -----------------------------------------

    def test_filter_does_not_modify_data(self):
        project = self.env["project.project"].create({"name": "F"})
        a = self._task(project, "A")
        b = self._task(project, "B", parent=a)
        before = (a.date_assign, a.date_deadline, b.parent_id, a.wbs_code, b.wbs_code)
        self._data(project, [["id", "=", b.id]])
        a.invalidate_recordset()
        b.invalidate_recordset()
        after = (a.date_assign, a.date_deadline, b.parent_id, a.wbs_code, b.wbs_code)
        self.assertEqual(before, after)

    def test_empty_filter_result(self):
        project = self.env["project.project"].create({"name": "F"})
        self._task(project, "A")
        data = self._data(project, [["name", "=", "No such task"]])
        self.assertEqual(data["tasks"], [])
        # The project payload still loads cleanly.
        self.assertEqual(data["project"]["id"], project.id)
