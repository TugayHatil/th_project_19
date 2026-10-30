# -*- coding: utf-8 -*-
{
    'name': "Purchase Order Revision Number",

    'summary': "Onaylanan satınalma siparişlerinde revizyon numarası takibi",

    'description': """Onaylanıp sonradan revize edilen satınalma siparişlerinin
revizyon numarasını otomatik günceller ve sipariş üzerinde
gösterir.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Inventory/Purchase',
    'version': '19.0.1.0.0',

    'depends': ['purchase'],

    'data': [
        'views/purchase_order_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,

}
