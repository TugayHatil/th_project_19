# -*- coding: utf-8 -*-

{
    "name": "Long-Term Production Planning",
    "summary": "12-month long-term production planning grid (OS/SM/GM/IM/PM/DS)",
    "version": "19.0.2.2.0",
    "category": "Manufacturing/Manufacturing",
    "author": "Projet Solutions",
    "license": "LGPL-3",
    "depends": ["mrp", "sale_stock"],

    "data": [
        "security/ir.model.access.csv",
        "data/decimal_precision.xml",
        "views/product_template_views.xml",
        "views/mrp_ltp_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mrp_long_term_planning/static/src/planning/long_term_planning.js",
            "mrp_long_term_planning/static/src/planning/long_term_planning.xml",
            "mrp_long_term_planning/static/src/planning/long_term_planning.scss",
        ],
    },
    "installable": True,
    "application": False,
}
