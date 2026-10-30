# -*- coding: utf-8 -*-
{
    'name': "Product Multi Manufacturer",

    'summary': "Ürünleri birden fazla üretici ve üretici kodu ile ilişkilendirme",

    'description': """Ürünün birden fazla üretici ile ilişkilendirilmesini sağlar;
her üretici için ayrı üretici kodu, not ve durum tutulur. Üretici
kodları için Stok > Ürünler altında merkezi bir Üretici Kodları
menüsü ekler.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Inventory/Inventory',
    'version': '19.0.1.0.0',

    'depends': [
        'product',
        'stock',
    ],

    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/product_manufacturer_views.xml',
        'views/product_product_views.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
