# -*- coding: utf-8 -*-
{
    'name': "Purchase Request View Customization",

    'summary': "Satınalma talebi görünümlerinde alan gizleme ve çeviri düzenlemeleri",

    'description': """Satınalma talebi görünümlerinde arayüz düzenlemeleri:

- Talep formunda date_start, origin, description alanları gizlenir.
- Talep formundaki satır listesinde estimated_cost, purchased_qty,
  purchase_state sütunları gizlenir.
- Talep liste görünümünde date_start, origin, activity_ids,
  estimated_cost sütunları gizlenir.
- Satınalma talep satırları menüsünde estimated_cost, purchased_qty,
  purchase_state, supplier_id sütunları gizlenir; name (açıklama)
  sütunu varsayılan gizli/opsiyonel olarak gelir.
- assigned_to alanının Türkçe çevirisi "Onaylayacak" yapılır.
- "Create RFQ" metinlerinin Türkçe çevirisi her yerde
  "Sipariş Oluştur" yapılır (aksiyon menüsü, form butonu, sihirbaz).""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Inventory/Purchase',
    'version': '19.0.1.0.0',

    'depends': [
        'purchase_request',
    ],

    'data': [
        'views/purchase_request_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
