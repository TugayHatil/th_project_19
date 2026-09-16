# -*- coding: utf-8 -*-

{
    "name": "Project Critical Path",
    "summary": "Calculate and store critical paths from task dependencies",
    "version": "19.0.1.31.0",
    "category": "Project",
    "author": "Projet Solutions",
    "license": "LGPL-3",
    "depends": ["project", "hr", "hr_timesheet", "maintenance", "web_gantt"],

    "data": [
        "security/ir.model.access.csv",
        "views/project_project_views.xml",
        "views/project_task_kanban.xml",
        "views/project_planner_views.xml",
    ],
    "demo": [
        "demo/project_wbs_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "project_critical_path/static/src/gantt_dependency_geometry.js",
            "project_critical_path/static/src/gantt_dependencies.js",
            "project_critical_path/static/src/gantt_dependencies.xml",
            "project_critical_path/static/src/gantt_dependencies.scss",
            "project_critical_path/static/src/scss/critical_path_kanban.scss",
            "project_critical_path/static/src/planner/planner_workspace.js",
            "project_critical_path/static/src/planner/planner_workspace.xml",
            "project_critical_path/static/src/planner/planner_workspace.scss",
        ],
    },
    "installable": True,

    "application": False,
}
