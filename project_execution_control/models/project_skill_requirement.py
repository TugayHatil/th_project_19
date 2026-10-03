# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProjectTaskSkillRequirement(models.Model):
    """Skill a task needs (BRD §7 — Skill / Resource Matching).

    Deliberately thin: the skill catalogue, levels and employee skill
    records all live in ``hr_skills`` — this row only says *what* the
    task needs and *how well covered* that need is. Coverage is a
    read-only analysis against the task's candidate employees; nothing
    here assigns, reassigns or schedules anyone.
    """

    _name = "project.task.skill.requirement"
    _description = "Project Task Skill Requirement"
    _order = "task_id, sequence, id"

    sequence = fields.Integer(default=10)
    task_id = fields.Many2one(
        "project.task", required=True, ondelete="cascade", index=True)
    project_id = fields.Many2one(
        "project.project", related="task_id.project_id",
        store=True, index=True, readonly=True)
    skill_id = fields.Many2one("hr.skill", required=True, index=True)
    skill_type_id = fields.Many2one(
        "hr.skill.type", related="skill_id.skill_type_id", readonly=True)
    # Optional minimum: any named level of the skill's own type. When
    # unset, mere possession of the skill counts as covered.
    required_level_id = fields.Many2one(
        "hr.skill.level", string="Required Level",
        domain="[('skill_type_id', '=', skill_type_id)]")
    required_progress = fields.Float(
        related="required_level_id.level_progress", readonly=True)
    is_optional = fields.Boolean(
        string="Optional",
        help="Nice-to-have skills count toward the match percentage but "
             "can never make a task unmatched.")

    # ---- coverage analysis -------------------------------------------------
    coverage_state = fields.Selection(
        [
            ("matched", "Covered"),
            ("partial", "Below Required Level"),
            ("missing", "Missing"),
        ],
        string="Coverage", compute="_compute_coverage",
    )
    best_progress = fields.Float(
        string="Best Progress (%)", compute="_compute_coverage",
        digits=(16, 0))
    covered_by = fields.Char(
        string="Covered By", compute="_compute_coverage")

    @api.depends(
        "skill_id", "required_level_id", "task_id",
        "task_id.user_ids", "task_id.resource_requirement_ids",
    )
    def _compute_coverage(self):
        employees_by_task = {}
        for task in self.mapped("task_id"):
            employees_by_task[task.id] = task._skill_candidate_employees()
        skills_by_task = {
            task_id: emps.mapped("current_employee_skill_ids")
            for task_id, emps in employees_by_task.items()
        }
        for req in self:
            valid = skills_by_task.get(
                req.task_id.id, self.env["hr.employee.skill"]
            ).filtered(lambda s: s.skill_id == req.skill_id)
            if not valid:
                req.coverage_state = "missing"
                req.best_progress = 0.0
                req.covered_by = False
                continue
            best = max(valid, key=lambda s: s.level_progress or 0.0)
            req.best_progress = best.level_progress or 0.0
            req.covered_by = ", ".join(
                sorted(set(valid.mapped("employee_id.name")))) or False
            if req.best_progress >= (req.required_progress or 0.0):
                req.coverage_state = "matched"
            else:
                req.coverage_state = "partial"
