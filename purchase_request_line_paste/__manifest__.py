# -*- coding: utf-8 -*-
{
    'name': "Purchase Request Line Paste",

    'summary': "Satınalma talebi satırlarına ürün kodu + miktar listesi yapıştırarak toplu satır ekleme",

    'description': """Satınalma talebi satır listesinde "Satır Ekle"nin
yanına Satır Yapıştır bağlantısı ekler. Excel'den kopyalanan
"ürün kodu + miktar" listesi (sekme ile ayrılmış) yapıştırılır; sihirbaz
her satırı doğrulayıp ürünleri kodlarından çözümleyerek önizleme listesi
sunar. Geçerli satırlar talebe standart satır olarak eklenir; hatalı
satırlar (ürün bulunamadı, geçersiz miktar, satınalınabilir değil)
listede işaretlenir ve atlanır. Miktarlar kullanıcının Odoo dil/biçim
ayarına göre ayrıştırılır.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Inventory/Purchase',
    'version': '19.0.1.5.0',

    'depends': [
        'purchase_request',
    ],

    'data': [
        'security/ir.model.access.csv',
        'views/purchase_request_line_paste_wizard_views.xml',
        'views/purchase_request_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
