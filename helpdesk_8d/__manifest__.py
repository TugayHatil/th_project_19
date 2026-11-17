# -*- coding: utf-8 -*-
{
    'name': "Helpdesk 8D - Problem Takip ve Kök Neden Analizi",

    'summary': "Ticket'a 8D detay alanları, Luna tanım tabloları ve 8D PDF çıktısı",

    'description': """Helpdesk ticket formuna 8D problem takip alanları ekler ve
ticket üzerinden "Problem Takip ve Kök Neden Analiz Formu (8D)" PDF çıktısı
alınmasını sağlar.

Yardım Masası / Yapılandırma menüsü altındaki "Luna" ara menüsünde üç yeni
tanım tablosu yönetilir: Farkedildiği Yerler, Donanım Versiyonları ve
Yazılım Versiyonları.

Ticket formuna eklenen alanlar: Farkedildiği Yer, Farketme Zamanı, Ürün
(mevcut alan gösterilir), Seri Numarası, Donanım Versiyonu ve Yazılım
Versiyonu. Açıklama sayfasından sonra "Detaylar", "Detaylı Analiz ve
Aksiyonlar" ve "Doğrulama ve Önlem" adlı üç yeni sayfa eklenir; sayfalardaki
tüm alanlar HTML türündedir.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Services/Helpdesk',
    'version': '19.0.1.0.0',

    'depends': [
        'helpdesk',
    ],

    'data': [
        'security/ir.model.access.csv',
        'views/noticed_location_views.xml',
        'views/hardware_version_views.xml',
        'views/software_version_views.xml',
        'views/helpdesk_ticket_views.xml',
        'views/helpdesk_8d_menus.xml',
        'report/helpdesk_8d_report.xml',
        'report/helpdesk_8d_report_templates.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
