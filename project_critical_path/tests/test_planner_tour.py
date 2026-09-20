# -*- coding: utf-8 -*-

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPlannerTour(HttpCase):
    """Browser regression for the Planner v1 certification tour
    (static/tests/tours/planner_workspace_tour.js): workspace open,
    continuous day timeline, WBS→Inspector, dependency arrows, today
    marker and Day/Week/Month scale switching."""

    def test_planner_workspace_certification_tour(self):
        project = self.env["project.project"].create({"name": "Planner Cert Tour Project"})
        first = self.env["project.task"].create({
            "name": "Cert Task A", "project_id": project.id, "allocated_hours": 8,
            "date_assign": "2026-09-15 09:00:00", "date_deadline": "2026-09-15 18:00:00",
        })
        self.env["project.task"].create({
            "name": "Cert Task B", "project_id": project.id, "allocated_hours": 8,
            "date_assign": "2026-09-15 18:00:00", "date_deadline": "2026-09-16 09:00:00",
            "depend_on_ids": [(4, first.id)],
        })
        self.start_tour(
            "/odoo/project/%s/action-project_critical_path.planner_workspace" % project.id,
            "planner_workspace_certification",
            login="admin",
        )
