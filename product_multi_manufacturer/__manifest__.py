# -*- coding: utf-8 -*-
{
    'name': "Product Multi Manufacturer",

    'summary': "Link products to multiple manufacturers and manufacturer codes.",

    'description': """Allows a product to be linked with multiple manufacturers, each with its own manufacturer code, note and status. Adds a central Manufacturer Codes menu under Inventory → Products.""",

    'author': "RADORP",
    'website': "https://radorp.com",

    'category': 'Inventory',
    'version': '19.0.1.0.0',

    'depends': [
        'product',
        'stock',
    ],

    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/product_manufacturer_views.xml',
        'views/product_product_views.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
