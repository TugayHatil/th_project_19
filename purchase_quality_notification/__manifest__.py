# -*- coding: utf-8 -*-
{
    'name': "Purchase Quality Notification",

    'summary': "Satınalma KK işaretli ürünler için otomatik kalite kontrol noktası, "
               "arıza konumu senkronizasyonu ve gelen transferden kalite ekibine tek butonla bildirim",

    'description': """Ürün kartındaki "Satınalma KK" işaretine bağlı olarak Odoo standart
kalite kontrol mekanizmasını otomatikleştirir.

- Satınalma KK işaretlenen her ürün için tek bir otomatik kalite kontrol
  noktası (quality.point) oluşturulur; işaret kaldırılınca nokta arşivlenir,
  tekrar işaretlenince yeniden etkinleşir. Yeni ürün varyantları noktaya
  otomatik dahil edilir.
- Stok konumlarına "Arıza Konumu mu?" işareti eklenir; işaretli tüm dahili
  konumlar otomatik kalite kontrol noktalarının Arıza Lokasyonları alanıyla
  senkron tutulur.
- Satınalma KK kapsamındaki ürün içeren gelen transferlerde "Kaliteye Gönder"
  butonu görünür; buton kalite ekibine (Quality / User grubu üyeleri) düzenlenebilir
  e-posta şablonu üzerinden bildirim gönderir ve gönderimi transferin
  chatter alanına kaydeder.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Inventory/Purchase',
    'version': '19.0.1.0.0',

    'depends': [
        'mail',
        'product_extra_fields',
        'purchase',
        'quality_control',
    ],

    'data': [
        'data/mail_template_data.xml',
        'views/product_template_views.xml',
        'views/stock_location_views.xml',
        'views/stock_picking_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
