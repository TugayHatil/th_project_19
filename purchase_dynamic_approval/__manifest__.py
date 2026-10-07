# -*- coding: utf-8 -*-
{
    'name': "Purchase Dynamic Approval",

    'summary': "Satınalma siparişlerinde tutar bazlı dinamik onay mekanizması",

    'description': """Satınalma siparişlerinde dinamik tutar bazlı onay mekanizması.

Tanımlanan tutar baremlerine göre her aralık için farklı bir Odoo
kullanıcı grubunun onaylayıcı olarak atanmasını sağlar. Standart PO
durum akışı korunur; onay standart "Onay Bekliyor" (to approve)
durumu üzerinden yürütülür. Onay geçmişi, zorunlu red nedeni,
aktivite bildirimleri ve tutar değişikliğinde yeniden onay
desteği içerir.""",

    'author': "RADORP",
    'website': "https://radorp.com",

    'category': 'Inventory/Purchase',
    'version': '19.0.1.0.0',

    'depends': [
        'purchase',
    ],

    'data': [
        'security/purchase_dynamic_approval_security.xml',
        'security/ir.model.access.csv',
        'data/purchase_dynamic_approval_data.xml',
        'views/purchase_approval_tier_views.xml',
        'views/purchase_order_views.xml',
        'views/purchase_order_reject_wizard_views.xml',
        'views/purchase_order_reject_reason_views.xml',
        'views/res_config_settings_views.xml',
        'views/purchase_dynamic_approval_menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
