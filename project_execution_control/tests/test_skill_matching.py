# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from odoo import fields


class TestSkillMatching(TransactionCase):
    """BRD SKILL-001..012 — task-level skill coverage analysis on top of
    hr_skills. Read-only: matching must never assign or reschedule."""

    def setUp(self):
        super().setUp()
        self.Req = self.env["project.task.skill.requirement"]
        self.skill_type = self.env["hr.skill.type"].create({"name": "ST Type"})
        self.lvl_junior = self.env["hr.skill.level"].create({
            "name": "Junior", "skill_type_id": self.skill_type.id,
            "level_progress": 20,
        })
        self.lvl_senior = self.env["hr.skill.level"].create({
            "name": "Senior", "skill_type_id": self.skill_type.id,
            "level_progress": 80,
        })
        self.skill_a, self.skill_b, self.skill_c = (
            self.env["hr.skill"].create([
                {"name": name, "skill_type_id": self.skill_type.id}
                for name in ("Skill A", "Skill B", "Skill C")
            ])
        )
        self.user_ok, self.emp_ok = self._person("ok", [
            (self.skill_a, self.lvl_senior),
            (self.skill_b, self.lvl_junior),
        ])
        self.user_weak, self.emp_weak = self._person("weak", [
            (self.skill_a, self.lvl_junior),
        ])
        self.project = self.env["project.project"].create({"name": "SKL"})

    # ── helpers ──────────────────────────────────────────────────────
    def _person(self, login, skills):
        user = self.env["res.users"].create({
            "name": "SKL %s" % login, "login": "skl_%s" % login,
        })
        employee = self.env["hr.employee"].create({
            "name": "Emp %s" % login, "user_id": user.id,
        })
        for skill, level in skills:
            self.env["hr.employee.skill"].create({
                "employee_id": employee.id,
                "skill_id": skill.id,
                "skill_level_id": level.id,
            })
        return user, employee

    def _task(self, name, users=None):
        task = self.env["project.task"].create({
            "name": name, "project_id": self.project.id,
        })
        if users:
            task.user_ids = [fields.Command.set([u.id for u in users])]
        return task

    def _req(self, task, skill, level=None, optional=False):
        return self.Req.create({
            "task_id": task.id,
            "skill_id": skill.id,
            "required_level_id": level.id if level else False,
            "is_optional": optional,
        })

    # ── states ───────────────────────────────────────────────────────
    def test_skill_001_no_requirement(self):
        """SKILL-001 — no skill requirements → not_required."""
        task = self._task("T1", users=[self.user_ok])
        self.assertEqual(task.skill_match_state, "not_required")
        self.assertEqual(task.skill_required_count, 0)

    def test_skill_002_single_skill_covered(self):
        """SKILL-002 — required level met by the assignee → matched."""
        task = self._task("T2", users=[self.user_ok])
        req = self._req(task, self.skill_a, self.lvl_senior)
        self.assertEqual(req.coverage_state, "matched")
        self.assertEqual(task.skill_match_state, "matched")
        self.assertEqual(task.skill_match_percentage, 100.0)

    def test_skill_003_level_insufficient(self):
        """SKILL-003 — skill present but level below → partial."""
        task = self._task("T3", users=[self.user_weak])
        req = self._req(task, self.skill_a, self.lvl_senior)
        self.assertEqual(req.coverage_state, "partial")
        self.assertEqual(req.best_progress, 20.0)
        self.assertEqual(task.skill_match_state, "partial")

    def test_skill_004_skill_missing(self):
        """SKILL-004 — skill absent on the assignee → unmatched."""
        task = self._task("T4", users=[self.user_weak])
        req = self._req(task, self.skill_b, self.lvl_junior)
        self.assertEqual(req.coverage_state, "missing")
        self.assertEqual(task.skill_match_state, "unmatched")

    def test_skill_005_mixed_coverage_partial(self):
        """SKILL-005 — some requirements met, some not → partial."""
        task = self._task("T5", users=[self.user_ok])
        self._req(task, self.skill_a, self.lvl_senior)   # covered
        self._req(task, self.skill_c, self.lvl_junior)   # missing
        self.assertEqual(task.skill_match_state, "partial")
        self.assertEqual(task.skill_matched_count, 1)
        self.assertEqual(task.skill_missing_count, 1)
        self.assertEqual(task.skill_match_percentage, 50.0)

    def test_skill_006_all_missing_unmatched(self):
        """SKILL-006 — every requirement missing → unmatched."""
        task = self._task("T6", users=[self.user_weak])
        self._req(task, self.skill_b)
        self._req(task, self.skill_c)
        self.assertEqual(task.skill_match_state, "unmatched")
        self.assertEqual(task.skill_missing_count, 2)

    def test_skill_007_no_assignee_never_matched(self):
        """SKILL-007 — requirements with nobody assigned → unmatched,
        never an optimistic matched."""
        task = self._task("T7")
        self._req(task, self.skill_a)
        self.assertEqual(task.skill_match_state, "unmatched")
        self.assertEqual(task.skill_matched_count, 0)

    def test_skill_008_reassign_recomputes(self):
        """SKILL-008 — changing the assignee re-evaluates coverage."""
        task = self._task("T8", users=[self.user_weak])
        self._req(task, self.skill_a, self.lvl_senior)
        self.assertEqual(task.skill_match_state, "partial")
        task.user_ids = [fields.Command.set([self.user_ok.id])]
        task.invalidate_recordset()
        self.assertEqual(task.skill_match_state, "matched")

    def test_skill_009_planner_payload_and_detail(self):
        """SKILL-009 — planner rows and the inspector carry the block."""
        task = self._task("T9", users=[self.user_ok])
        self._req(task, self.skill_a, self.lvl_senior)
        data = self.project.get_planner_data()
        row = {r["id"]: r for r in data["tasks"]}[task.id]
        self.assertEqual(row["skill_match_state"], "matched")
        self.assertIn("skill_match_percentage", row)
        detail = task.get_planner_detail()
        self.assertIn("skills", detail)
        self.assertEqual(detail["skills"]["skill_match_state"], "matched")
        self.assertEqual(len(detail["skills"]["requirements"]), 1)
        self.assertIn("Emp ok", detail["skills"]["candidates"])

    def test_skill_010_search_filters(self):
        """SKILL-010 — the non-stored state stays usable in domains."""
        matched = self._task("TM", users=[self.user_ok])
        self._req(matched, self.skill_a, self.lvl_senior)
        missing = self._task("TU", users=[self.user_weak])
        self._req(missing, self.skill_b)
        plain = self._task("TN")
        matched.invalidate_recordset()
        missing.invalidate_recordset()
        found = self.env["project.task"].search(
            [("skill_match_state", "=", "unmatched")])
        self.assertIn(missing, found)
        self.assertNotIn(matched, found)
        self.assertNotIn(plain, found)

    def test_skill_011_resource_plan_untouched(self):
        """SKILL-011 — adding skill requirements must not alter resource
        requirements, assignments or task dates."""
        task = self._task("T11", users=[self.user_ok])
        role = self.env["project.resource.role"].create(
            {"name": "SKL Role"})
        requirement = self.env["project.task.resource.requirement"].create({
            "task_id": task.id, "role_id": role.id, "quantity": 1,
        })
        assignment = self.env["project.task.resource.assignment"].create({
            "requirement_id": requirement.id,
            "employee_id": self.emp_ok.id,
        })
        before = (task.resource_requirement_ids.ids,
                  requirement.assignment_ids.ids)
        self._req(task, self.skill_a, self.lvl_senior)
        task.invalidate_recordset()
        self.assertEqual(task.resource_requirement_ids.ids, before[0])
        self.assertEqual(requirement.assignment_ids.ids, before[1])
        self.assertTrue(assignment.exists())
        # Assigned employee also counts as a candidate.
        self.assertEqual(task.skill_match_state, "matched")

    def test_skill_012_optional_never_unmatched(self):
        """Optional requirements warn but never flip a task unmatched."""
        task = self._task("T12", users=[self.user_weak])
        self._req(task, self.skill_c, optional=True)
        self.assertEqual(task.skill_match_state, "partial")
        self.assertEqual(task.skill_required_count, 0)
