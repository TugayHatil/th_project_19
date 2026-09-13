# -*- coding: utf-8 -*-
{
    'name': 'Construction Management',
    'version': '19.0.1.0.0',
    'summary': 'Manage BOQ, WBS, Work Orders, Billing, Quality & more',
    'description': """
Construction Management System
================================
A comprehensive module for managing construction projects including:
- Construction Projects with smart buttons
- BOQ (Bill of Quantities) with line items
- WBS Phases (Work Breakdown Structure)
- Work Orders management
- Material Requisitions
- Subcontracting
- RA Billing (Running Account)
- Progress Billing
- Quality Checks with checklists
- Expenses tracking
- OWL Dashboard

Contact Information:
- Email: abdzoro89@gmail.com / a.osman@bab.com.sa
- Phone: +966562984106 / +966553368212
    """,
    'category': 'Construction',
    'author': 'leapai.ai',
    'website': 'https://leapai.ai',
    'support': 'abdzoro89@gmail.com',
    'maintainer': 'a.osman@bab.com.sa',
    'depends': ['base', 'mail', 'product', 'uom', 'account'],
    'data': [
        'security/construction_security.xml',
        'security/ir.model.access.csv',
        'views/construction_project_views.xml',
        'views/construction_boq_views.xml',
        'views/construction_wbs_views.xml',
        'views/construction_work_order_views.xml',
        'views/construction_material_requisition_views.xml',
        'views/construction_subcontract_views.xml',
        'views/construction_billing_views.xml',
        'views/construction_quality_check_views.xml',
        'views/construction_expense_views.xml',
        'views/construction_dashboard_views.xml',
        'views/construction_menu.xml',
        'report/construction_boq_report.xml',
        'report/construction_boq_report_template.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'aos_construction_management/static/src/js/construction_dashboard.js',
            'aos_construction_management/static/src/xml/construction_dashboard.xml',
        ],
    },
    'demo': ['demo/construction_demo.xml'],
    'post_init_hook': 'post_init_hook',
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
    'images': ['static/description/icon.png'],
}
