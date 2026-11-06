# -*- coding: utf-8 -*-
{
    'name': "Sale Order Forecast Nature",

    'summary': "Satış siparişlerinde Öngörü niteliği: teslimat emri oluşturmadan onay ve tek tuşla Kesinleşmiş siparişe dönüştürme",

    'description': """Satış siparişlerine Sipariş Niteliği (Kesinleşmiş / Öngörü) alanı ekler.

Öngörü niteliğindeki teklifler standart onay sürecinden geçerek Sales Order
durumuna gelir ancak teslimat emri, stok rezervasyonu veya stok hareketi
oluşturulmaz. Sipariş onaylandığında stok kuralları tetiklenmez.

Onaylanmış Öngörü siparişi formundaki "Kesinleşmiş Siparişe Dönüştür" butonu
ile sipariş aynı numara ve satırlarla Kesinleşmiş niteliğe çevrilir;
dönüştürme anında standart Odoo teslimat süreci başlatılır ve işlem
chatter'a yazılır. Dönüştürme tek yönlüdür ve her sipariş için yalnızca
bir kez yapılabilir.

Öngörü niteliğindeki siparişlerden fatura oluşturulamaz; dönüştürme
sonrasında standart faturalama süreci kullanılır.

Mevcut Satış Sipariş Türü (sale_order_type_journal) alanından bağımsız
çalışır; stok tahmini, rezervasyon ve MRP mekanizmalarına müdahale etmez.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Sales/Sales',
    'version': '19.0.1.2.0',

    'depends': [
        'sale_stock',
    ],

    'data': [
        'views/sale_order_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sale_order_forecast/static/src/scss/sale_order_forecast.scss',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
