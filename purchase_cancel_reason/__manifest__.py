# -*- coding: utf-8 -*-
{
    'name': "Purchase Cancel Reason",

    'summary': "Satınalma siparişi iptalinde neden seçimi ve iptal analizi",

    'description': """Satınalma siparişlerinin iptalinde standartlaştırılmış
İptal Nedeni alınması ve iptal bilgilerinin raporlanması.

Sent, To Approve ve Purchase aşamalarında İptal Et aksiyonu İptal
Nedeni popup'ı açar; neden seçilmeden iptal tamamlanamaz. "Diğer"
nedeni seçildiğinde açıklama zorunludur. İptal edilen aşama, iptal
eden kullanıcı ve iptal tarihi otomatik kaydedilir, "Diğer Bilgiler"
sekmesinde gösterilir ve chatter'a yazılır. İptal edilen siparişler
Satınalma > Raporlama > İptal Analizi altında neden, aşama, kullanıcı
ve tarih kırılımlarında analiz edilebilir.""",

    'author': "RADORP",
    'website': "https://radorp.com",

    'category': 'Inventory/Purchase',
    'version': '19.0.1.0.0',

    'depends': [
        'purchase',
    ],

    'data': [
        'security/ir.model.access.csv',
        'data/purchase_order_cancel_reason_data.xml',
        'views/purchase_order_cancel_reason_views.xml',
        'views/purchase_order_cancel_wizard_views.xml',
        'views/purchase_order_views.xml',
        'views/purchase_cancel_analysis_views.xml',
        'views/purchase_cancel_reason_menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
