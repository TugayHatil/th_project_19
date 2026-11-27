# -*- coding: utf-8 -*-
{
    'name': "Purchase Expected Loading Date",

    'summary': "Satınalma siparişlerinde sevk türü ve beklenen yükleme tarihi",

    'description': """Satınalma siparişlerinde sevk türü ve beklenen yükleme tarihi.

Satınalma siparişinin Diğer Bilgiler sekmesine Sevk Türü alanı ekler
(Denizyolu, Havayolu, Karayolu, Demiryolu). Sipariş başlığına ve satırlarına
Beklenen Yükleme tarihi ekler; beklenen geliş tarihiyle aynı mantıkta çalışır
(başlıktan satırlara uygulanır, satırda değiştirilen geçerlidir).

Tedarikçi fiyat listesi satırında sevk türü başına transit süre (gün)
tanımlanabilir. Siparişte sevk türü seçildiğinde her satırın beklenen yükleme
tarihi = beklenen geliş - ilgili transit süre olarak otomatik hesaplanır.

Beklenen yükleme tarihi transfer (stok hareketi) satırlarına da taşınır;
planlanan tarih gibi çalışır.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Inventory/Purchase',
    'version': '19.0.1.0.0',

    'depends': [
        'purchase_stock',
    ],

    'data': [
        'security/ir.model.access.csv',
        'views/product_supplierinfo_views.xml',
        'views/purchase_order_views.xml',
        'views/stock_picking_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
