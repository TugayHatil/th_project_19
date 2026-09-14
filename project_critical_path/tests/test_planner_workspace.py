# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase


class TestPlannerWorkspace(TransactionCase):
    """Planner Workspace data API: WBS ordering, dates, hierarchy flags."""

    def _make_task(self, project, name, parent=None, **values):
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
            "parent_id": parent.id if parent else False,
            **values,
        })

    def test_planner_data_returns_tasks_in_wbs_order(self):
        project = self.env["project.project"].create({"name": "Planner order"})
        eng = self._make_task(project, "Engineering",
                              date_assign="2026-03-01 09:00:00", date_deadline="2026-03-31 18:00:00")
        drawing = self._make_task(project, "Drawing", parent=eng,
                                  date_assign="2026-03-01 09:00:00", date_deadline="2026-03-10 18:00:00")
        detail = self._make_task(project, "Detail Drawing", parent=drawing,
                                 date_assign="2026-03-02 09:00:00", date_deadline="2026-03-06 18:00:00")
        approval = self._make_task(project, "Approval", parent=eng,
                                   date_assign="2026-03-11 09:00:00", date_deadline="2026-03-17 18:00:00")
        procurement = self._make_task(project, "Procurement",
                                      date_assign="2026-04-01 09:00:00", date_deadline="2026-04-10 18:00:00")

        data = project.get_planner_data()

        self.assertEqual(data["project"]["id"], project.id)
        rows = {row["wbs_code"]: row for row in data["tasks"]}
        self.assertEqual([row["wbs_code"] for row in data["tasks"]], ["1", "1.1", "1.1.1", "1.2", "2"])
        self.assertEqual(rows["1"]["name"], "Engineering")
        self.assertTrue(rows["1"]["has_children"])
        self.assertTrue(rows["1.1"]["has_children"])
        self.assertFalse(rows["1.1.1"]["has_children"])
        self.assertEqual(rows["1.1.1"]["parent_id"], drawing.id)
        self.assertEqual(rows["1.2"]["parent_id"], eng.id)
        self.assertFalse(rows["2"]["parent_id"])
        self.assertEqual(rows["1.1.1"]["wbs_level"], 3)
        self.assertEqual(rows["1"]["date_start"], "2026-03-01")
        self.assertEqual(rows["1"]["date_stop"], "2026-03-31")
        self.assertEqual(rows["2"]["date_stop"], "2026-04-10")

    def test_planner_data_serializes_missing_dates_as_false(self):
        project = self.env["project.project"].create({"name": "Undated planner"})
        self._make_task(project, "No dates task")

        row = project.get_planner_data()["tasks"][0]

        self.assertFalse(row["date_start"])
        self.assertFalse(row["date_stop"])

    def test_action_open_planner_workspace_returns_client_action(self):
        project = self.env["project.project"].create({"name": "Planner action"})

        action = project.action_open_planner_workspace()

        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "project_critical_path.planner_workspace")
        self.assertEqual(action["params"]["project_id"], project.id)

    def test_get_planner_projects_lists_projects(self):
        project = self.env["project.project"].create({"name": "Listed project"})

        projects = self.env["project.project"].get_planner_projects()

        self.assertIn(
            {"id": project.id, "name": project.display_name},
            [{"id": entry["id"], "name": entry["name"]} for entry in projects],
        )
