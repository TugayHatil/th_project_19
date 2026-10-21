# -*- coding: utf-8 -*-

{
    "name": "Material Need & Purchase Planning",
    "summary": "Product-grouped material need planning screen with merged purchase requests",
    "version": "19.0.1.0.0",
    "category": "Manufacturing/Manufacturing",
    "author": "Projet Solutions",
    "license": "LGPL-3",
    "depends": ["mrp", "purchase_request"],

    "data": [
        "views/product_template_views.xml",
        "views/res_config_settings_views.xml",
        "views/purchase_request_line_views.xml",
        "views/mrp_purchase_need_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mrp_purchase_need_plan/static/src/need_plan/need_plan.js",
            "mrp_purchase_need_plan/static/src/need_plan/need_plan.xml",
            "mrp_purchase_need_plan/static/src/need_plan/need_plan.scss",
        ],
    },
    "installable": True,
    "application": False,
}
