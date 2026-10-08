# -*- coding: utf-8 -*-
{
    'name': "Supplier Document Expiry",

    'summary': "Tedarikçi belgelerinin geçerlilik takibi ve otomatik durum uyarıları",

    'description': """Tedarikçi belgelerinin merkezi yönetimi ve geçerlilik takibi.

Belge türü bazında dinamik sarı/turuncu uyarı günleri tanımlanır;
her belge kaydına birden fazla dosya eklenebilir. Geçerlilik
tarihine göre yeşil/sarı/turuncu/kırmızı durumu otomatik hesaplanır.
Seviye değişimlerinde sorumlu kullanıcıya aktivite ile uyarı
üretilir. Okuma / Kullanıcı / Yönetici olmak üzere üç yetki seviyesi
içerir; okuma grubu belge dosyalarını indiremez.""",

    'author': "RADORP",
    'website': "https://radorp.com",

    'category': 'Inventory/Purchase',
    'version': '19.0.1.0.0',

    'depends': [
        'purchase',
        'mail',
    ],

    'data': [
        'security/supplier_document_expiry_security.xml',
        'security/ir.model.access.csv',
        'data/supplier_document_data.xml',
        'views/supplier_document_type_views.xml',
        'views/supplier_document_views.xml',
        'views/res_partner_views.xml',
        'views/supplier_document_expiry_menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
