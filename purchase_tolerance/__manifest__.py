# -*- coding: utf-8 -*-
{
    'name': "Purchase Tolerance",

    'summary': "Satınalma toleransı ve fazla teslimat yönetimi",

    'description': """Satınalma toleransı ve fazla teslimat yönetimi.

Genel ayar, ürün ve satınalma siparişi satırı seviyesinde tolerans yönetimi.
Mal kabul doğrulamasında tolerans kontrolü, tolerans aşımı talebi oluşturma
ve satınalma yöneticisi onay/red akışı içerir.""",

    'author': "RADORP",
    'website': "https://radorp.com",

    'category': 'Inventory',
    'version': '19.0.1.0.0',

    'depends': [
        'purchase_stock',
    ],

    'data': [
        'security/purchase_tolerance_security.xml',
        'security/ir.model.access.csv',
        'data/purchase_tolerance_data.xml',
        'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
        'views/purchase_order_views.xml',
        'views/purchase_tolerance_request_views.xml',
        'views/purchase_tolerance_request_wizard_views.xml',
        'views/purchase_tolerance_menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
