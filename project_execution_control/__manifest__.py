# -*- coding: utf-8 -*-

{
    "name": "Project Execution Control",
    "summary": "Actual tracking, schedule variance and project control KPIs",
    "version": "19.0.1.0.0",
    "category": "Project",
    "author": "Projet Solutions",
    "license": "LGPL-3",
    # Phase 1 — Actual Tracking. Sits at the end of the one-directional
    # dependency chain; neither core addon is modified. Later phases
    # (material delay, skills, cost, change requests) extend this list.
    "depends": ["project_critical_path"],

    "data": [
        "views/project_task_views.xml",
        "views/project_project_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "project_execution_control/static/src/planner/planner_workspace_actual.js",
            "project_execution_control/static/src/planner/planner_workspace_actual.xml",
            "project_execution_control/static/src/planner/planner_workspace_actual.scss",
        ],
    },
    "installable": True,

    "application": False,
}
