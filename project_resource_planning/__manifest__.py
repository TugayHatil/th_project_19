# -*- coding: utf-8 -*-

{
    "name": "Project Resource Planning",
    "summary": "Human/equipment resource planning, Resource Board and Material Plan for projects",
    "version": "19.0.1.0.0",
    "category": "Project",
    "author": "Projet Solutions",
    "license": "LGPL-3",
    # Depends on the core planner: project_critical_path must work without
    # this addon; the dependency arrow never points the other way.
    "depends": ["project_critical_path", "hr", "maintenance", "product", "stock"],

    "data": [
        "security/ir.model.access.csv",
        "views/project_resource_role_views.xml",
        "views/project_resource_rate_views.xml",
        "views/project_material_plan_views.xml",
        "views/project_project_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "project_resource_planning/static/src/fields/material_transfer_badge.js",
            "project_resource_planning/static/src/fields/material_transfer_badge.xml",
            "project_resource_planning/static/src/fields/material_transfer_badge.scss",
            "project_resource_planning/static/src/planner/planner_workspace_resource.js",
            "project_resource_planning/static/src/planner/planner_workspace_resource.scss",
        ],
    },
    "installable": True,

    "application": False,
}
