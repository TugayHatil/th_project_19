# -*- coding: utf-8 -*-

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user


class TestPlannerManagerSecurity(TransactionCase):
    """BRD Planner Manager — members keep full Planner write access;
    every other user gets a strictly read-only Planner. The gate is
    enforced server-side on every mutation path, never by the UI alone.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group = cls.env.ref("project_critical_path.group_planner_manager")
        cls.project_group = cls.env.ref("project.group_project_user")
        cls.manager_user = new_test_user(
            cls.env, "planner_manager_user",
            groups="project.group_project_user,project_critical_path.group_planner_manager",
        )
        cls.viewer_user = new_test_user(
            cls.env, "planner_viewer_user",
            groups="project.group_project_user",
        )
        cls.project = cls.env["project.project"].create({"name": "Secured"})
        cls.task = cls.env["project.task"].create({
            "name": "Secured task",
            "project_id": cls.project.id,
            "date_assign": "2026-10-16 09:00:00",
            "date_deadline": "2026-10-18 18:00:00",
        })

    # -- group ----------------------------------------------------------------

    def test_group_exists(self):
        """The Planner Manager group is installed with the expected name."""
        self.assertEqual(self.group.name, "Planner Manager")

    def test_payload_exposes_membership(self):
        """get_planner_data tells the UI which mode to render — members get
        is_planner_manager=True, viewers False."""
        data_manager = self.project.with_user(self.manager_user).get_planner_data()
        data_viewer = self.project.with_user(self.viewer_user).get_planner_data()
        self.assertTrue(data_manager["is_planner_manager"])
        self.assertFalse(data_viewer["is_planner_manager"])

    # -- read paths stay open --------------------------------------------------

    def test_viewer_reads_planner(self):
        """Non-members keep every read path: payload, detail, history."""
        project = self.project.with_user(self.viewer_user)
        self.assertTrue(project.get_planner_data()["tasks"])
        task = self.task.with_user(self.viewer_user)
        self.assertEqual(task.get_planner_detail()["task"]["id"], self.task.id)
        project.get_planner_baseline_history()

    # -- planner RPC mutations -------------------------------------------------

    def test_viewer_cannot_update_planner_task(self):
        with self.assertRaises(AccessError):
            self.task.with_user(self.viewer_user).update_planner_task(
                {"date_start": "2026-10-20", "date_stop": "2026-10-21"}
            )

    def test_viewer_cannot_update_dependency(self):
        other = self.env["project.task"].create(
            {"name": "Other", "project_id": self.project.id}
        )
        with self.assertRaises(AccessError):
            self.task.with_user(self.viewer_user).update_planner_dependency(
                other.id, "fs", 0, "hours"
            )

    def test_viewer_cannot_wbs_mutations(self):
        """Subtask create, indent, outdent, reorder — all gated."""
        task = self.task.with_user(self.viewer_user)
        with self.assertRaises(AccessError):
            task.planner_add_subtask()
        second = self.env["project.task"].create(
            {"name": "Second", "project_id": self.project.id}
        ).with_user(self.viewer_user)
        with self.assertRaises(AccessError):
            second.planner_wbs_indent()
        with self.assertRaises(AccessError):
            self.task.with_user(self.viewer_user).planner_wbs_outdent()
        with self.assertRaises(AccessError):
            second.planner_wbs_move_before(self.task.id)

    def test_viewer_cannot_create_baseline(self):
        with self.assertRaises(AccessError):
            self.project.with_user(
                self.viewer_user
            ).action_create_critical_path_baseline()

    def test_viewer_cannot_write_dependency_rows(self):
        """Direct project.task.dependency create/write/unlink is blocked."""
        other = self.env["project.task"].create(
            {"name": "Dep", "project_id": self.project.id}
        )
        Dependency = self.env["project.task.dependency"].with_user(self.viewer_user)
        with self.assertRaises(AccessError):
            Dependency.create({
                "task_id": self.task.id,
                "depends_on_id": other.id,
            })

    # -- ordinary task form / RPC writes ---------------------------------------

    def test_viewer_cannot_write_planner_fields(self):
        """The guarded field set is blocked through plain write() too —
        task form and RPC are covered by the same gate."""
        task = self.task.with_user(self.viewer_user)
        for vals in (
            {"name": "Renamed"},
            {"date_assign": "2026-10-20 09:00:00"},
            {"date_deadline": "2026-10-21 18:00:00"},
            {"allocated_hours": 40.0},
            {"sequence": 99},
            {"user_ids": [(6, 0, [self.viewer_user.id])]},
            {"depend_on_ids": [(6, 0, [])]},
            {"dependent_ids": [(6, 0, [])]},
            {"parent_id": False},
            # date_done is readonly — no UI/RPC surface writes it; the
            # done/reopen stamp is driven by the state compute.
        ):
            with self.assertRaises(AccessError):
                task.write(vals)

    def test_viewer_can_write_unrelated_fields(self):
        """Non-planner task fields still follow Odoo's own permissions —
        closing a task via state is a task operation, not a planner edit."""
        stage = self.env["project.task.type"].search(
            [("fold", "=", True)], limit=1
        )
        if not stage:
            self.skipTest("No folded stage available")
        task = self.task.with_user(self.viewer_user)
        task.write({"stage_id": stage.id})
        self.assertEqual(task.stage_id, stage)

    def test_viewer_cannot_create_task_with_planner_fields(self):
        with self.assertRaises(AccessError):
            self.env["project.task"].with_user(self.viewer_user).create({
                "name": "Sneaky",
                "project_id": self.project.id,
                "date_assign": "2026-10-20 09:00:00",
            })

    def test_reopen_clears_date_done(self):
        """Finish Variance: reopening the task — through ANY path — clears
        the tail. ``date_done`` is computed from ``state`` so a stage-only
        reopen (no explicit state write) clears it too."""
        self.task.write({"state": "1_done"})
        self.assertTrue(self.task.date_done)
        self.task.write({"state": "01_in_progress"})
        self.assertFalse(self.task.date_done)
        # Done again → fresh stamp; explicit historical value is preserved.
        self.task.write({"state": "1_done"})
        self.assertTrue(self.task.date_done)

    def test_viewer_cannot_unlink_planned_task(self):
        """Deleting a scheduled task deletes planner data — blocked.
        A bare task with no planner footprint stays deletable."""
        with self.assertRaises(AccessError):
            self.task.with_user(self.viewer_user).unlink()
        bare = self.env["project.task"].create(
            {"name": "Bare", "project_id": self.project.id}
        )
        bare.with_user(self.viewer_user).unlink()
        self.assertFalse(bare.exists())

    def test_viewer_cannot_change_planner_settings(self):
        """planning_precision is planner configuration — gated too."""
        with self.assertRaises(AccessError):
            self.project.with_user(self.viewer_user).write(
                {"planning_precision": "day"}
            )

    # -- members keep everything -----------------------------------------------

    def test_manager_full_access(self):
        """Planner Manager members run the whole mutation surface."""
        task = self.task.with_user(self.manager_user)
        task.update_planner_task({
            "date_start": "2026-10-20",
            "date_stop": "2026-10-21",
            "duration_days": 2,
        })
        self.assertEqual(task.date_assign.day, 20)
        child = task.planner_add_subtask("Child")
        self.assertTrue(child["id"])
        self.project.with_user(
            self.manager_user
        ).action_create_critical_path_baseline("Rev A")
        self.assertTrue(self.project.critical_path_baseline_ids)
