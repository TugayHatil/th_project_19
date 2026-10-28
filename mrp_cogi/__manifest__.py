# -*- coding: utf-8 -*-
{
    'name': "COGI - Üretim Hareket Hataları",

    'summary': "Eksik bileşen tüketimlerini COGI kayıtları olarak izleme, yeniden işleme ve düzeltmeden kapatma",

    'description': """Üretim emri tamamlanırken reçetede planlanan bileşen tüketimi ile
fiilen gerçekleşen tüketim arasındaki farklar için COGI kayıtları
oluşturur.

Üretim / Üretim Raporlama / COGI menüsü altında farklar izlenir;
kullanıcı stok durumuna göre eksik miktarı "Yeniden İşle" aksiyonuyla
yeni bir stok hareketi olarak işleyebilir veya kaydı düzeltmeden
kapatabilir. COGI kaynaklı düzeltme hareketleri stok hareketleri
listesinde filtrelenir ve üretim emri akıllı butonu üzerinden
izlenebilir.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Manufacturing/Manufacturing',
    'version': '19.0.1.0.0',

    'depends': [
        'mrp',
    ],

    'data': [
        'security/ir.model.access.csv',
        'data/mrp_cogi_data.xml',
        'wizard/mrp_cogi_close_wizard_views.xml',
        'views/mrp_cogi_record_views.xml',
        'views/mrp_production_views.xml',
        'views/stock_move_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
