# -*- coding: utf-8 -*-
{
    'name': "İhale Yönetimi",

    'summary': "Satış teklifleriyle entegre ihale kayıtları: ihale takibi ve teklif oluşturma",

    'description': """Müşteri ihalelerinin merkezi takibi için İhale Yönetimi.

Satış uygulaması altında İhale Yönetimi menüsü ekler. Her ihale için ihale
numarası, adı, müşteri, tarihler, durum (Hazırlık / Teklif Verildi /
Kazanıldı / Kaybedildi / İptal), sorumlu, açıklama ve doküman ekleri
içeren bağımsız bir ihale kaydı tutulur.

İhale formundaki Teklifler smart button'u bağlı satış tekliflerini
listeler; Teklif Oluştur butonu müşteri, satış türü (İhale), ihale
bağlantısı ve sorumlu bilgileri önceden dolu standart satış teklifi
formunu açar.

sale.order modeline İhale alanı eklenir. Mevcut Satış Türü (so_type_id)
yapısı kullanılır; modül "İhale" tür kaydını data olarak ekler. Satış türü
"İhale" olduğunda ihale seçimi zorunludur ve yalnızca ilgili müşterinin
ihaleleri seçilebilir. Teklif revizyonlarında (copy) satış türü ve ihale
bağlantısı korunur.

Bağlı teklifi bulunan ihale kayıtları silinemez. İhale Kullanıcısı
grubu salt okunur erişim, İhale Yöneticisi grubu tam yetki sağlar.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Sales/Sales',
    'version': '19.0.1.1.0',

    'depends': [
        'sale',
        'sale_order_type_journal',
    ],

    'data': [
        'security/sale_tender_security.xml',
        'security/ir.model.access.csv',
        'data/sale_tender_data.xml',
        'views/sale_tender_views.xml',
        'views/sale_order_views.xml',
        'views/sale_tender_menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
