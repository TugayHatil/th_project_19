# -*- coding: utf-8 -*-

{
    "name": "Project UX",
    "summary": "Critical Path highlights and other UX improvements for project views",
    "version": "19.0.1.0.0",
    "category": "Project",
    "author": "Projet Solutions",
    "license": "LGPL-3",
    "depends": ["project", "project_critical_path"],

    "data": [
        "views/project_task_kanban.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "project_ux/static/src/scss/project_ux_kanban.scss",
        ],
    },
    "installable": True,
    "application": False,
}
