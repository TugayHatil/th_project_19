# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Drop the removed Material Requirement SQL view (BRD: the
    project.material.requirement model is gone — its DB view must not
    linger as an orphan object)."""
    cr.execute("DROP VIEW IF EXISTS project_material_requirement CASCADE")
    cr.execute("DROP TABLE IF EXISTS project_material_requirement CASCADE")
