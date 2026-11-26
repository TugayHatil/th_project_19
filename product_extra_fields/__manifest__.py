# -*- coding: utf-8 -*-
{
    'name': "Ürün Kartı Ek Alanları",

    'summary': "Ürün kartına ek sınıflandırma, sorumluluk, depo, kalite kontrol ve satınalma alanları ile tanım modelleri",

    'description': """Ürün kartına (product.template) operasyonel ihtiyaçlara göre ek
alanlar ekler ve bu alanlarda kullanılan merkezi tanım modellerini sağlar.

Eklenen ürün alanları: Eski Malzeme No, Alt Ürün Türü, Mal Grubu, Harici
Mal Grubu, Geçerlilik Başlangıç tarihi, MİP No ve MİP Sorumlusu (otomatik),
Üretim Sorumlusu No ve Üretim Sorumlusu (otomatik), Üretim Depo Yeri,
Dışarıdan Tedarik Depo Yeri, Üretim/Satınalma Kalite Kontrol işaretleri,
Satınalma Katları ve Satınalma Grubu. Diğer sekmesinde ayrıca MOQ, SPQ,
Leadtime, Emniyet Stoğu, Satınalma/Satış Yük Grubu (iç konumlar) ve
Dış Ticaret Grubu (İthalat/İhracat) alanları bulunur.

Tanım modelleri (Alt Ürün Türleri, Mal Grupları, Harici Mal Grupları,
MİP Sorumluları, Üretim Sorumluları) Stok / Ayarlar / Ürünler menüsü
altında yönetilir. Alt ürün türü, mal grubu ve harici mal grubu
formlarındaki smartbuton üzerinden o tanıma bağlı ürünler listelenebilir.
Sorumlu koduna bağlı sorumlu bilgisi değiştiğinde bu bilgi, kodu kullanan
bütün ürün kartlarında otomatik olarak güncellenir.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Inventory/Inventory',
    'version': '19.0.1.3.0',

    'depends': [
        'product',
        'stock',
        'purchase',
        'mail',
    ],

    'data': [
        'security/product_extra_fields_groups.xml',
        'security/ir.model.access.csv',
        'views/product_sub_type_views.xml',
        'views/product_material_group_views.xml',
        'views/product_external_material_group_views.xml',
        'views/mip_definition_views.xml',
        'views/production_supervisor_views.xml',
        'views/product_template_views.xml',
        'views/product_extra_fields_menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
