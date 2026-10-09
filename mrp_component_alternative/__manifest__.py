# -*- coding: utf-8 -*-
{
    'name': "MRP Component Alternatives",

    'summary': "BOM bileşenleri için alternatif malzeme tanımı, Replenishment'ta stok ikonu ve üretim emrinde onaylı alternatif seçimi",

    'description': """Ürün ağacı (BOM) bileşen satırlarına birden fazla alternatif
malzeme (öncelik + aktif bayrağı ile) tanımlanabilir.

Replenishment ekranında alternatifi olan ürünler ikon ile işaretlenir;
ikon alternatiflerin kullanılabilir stoklarını ve sistem önerisini
gösteren bir pencere açar.

Üretim emri onaylandığında ana malzemesi yetersiz olan satırlar için
alternatif seçim sihirbazı otomatik açılır (üretim emri üzerindeki
"Alternatifler" butonu ile de erişilebilir). Sistem ihtiyacın tamamını
karşılayan ilk alternatifi önceliğe göre önerir; nihai seçim ve onay
kullanıcıdadır. Onaylanan alternatif bileşen satırına uygulanır,
rezervasyon seçilen ürün üzerinden yapılır ve değişiklik üretim emri
chatter'ına yazılır.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Manufacturing/Manufacturing',
    'version': '19.0.1.0.0',

    'depends': [
        'mrp',
    ],

    'data': [
        'security/mrp_component_alternative_security.xml',
        'security/ir.model.access.csv',
        'wizard/mrp_alternative_selector_views.xml',
        'views/mrp_bom_views.xml',
        'views/mrp_production_views.xml',
        'views/stock_orderpoint_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mrp_component_alternative/static/src/scss/alternative_selector.scss',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
