# -*- coding: utf-8 -*-

{
    "name": "Project Critical Path",
    "summary": "Calculate and store critical paths from task dependencies",
    "version": "19.0.1.9.0",
    "category": "Project",
    "author": "Projet Solutions",
    "license": "LGPL-3",
    "depends": ["project", "hr", "hr_timesheet", "maintenance"],

    "data": [
        "security/ir.model.access.csv",
        "views/project_project_views.xml",
        "views/project_task_kanban.xml",
    ],
    "demo": [
        "demo/project_wbs_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "project_critical_path/static/src/scss/critical_path_kanban.scss",
        ],
    },
    "installable": True,

    "application": False,
}
