# -*- coding: utf-8 -*-
{
    'name': "Purchase Order Revision Number",

    'summary': "This module adds a Revision number to the Purchase Order.",

    'description': """This module updates the revision number of the purchase orders which have been confirmed and being revised.""",

    'author': "RADORP",
    'website': "https://radorp.com",
    
    'category': 'Uncategorized',
    'version': '19.0.1.0.0',

    'depends': ['base', 'purchase'],

    'data': [
        'views/purchase_order_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,

}
