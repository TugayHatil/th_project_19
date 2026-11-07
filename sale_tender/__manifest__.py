# -*- coding: utf-8 -*-
{
    'name': "İhale Yönetimi",

    'summary': "Satış teklifleriyle entegre ihale kayıtları: ihale takibi, teklif oluşturma ve satış türü sınıflandırması",

    'description': """Müşteri ihalelerinin merkezi takibi için İhale Yönetimi.

Satış uygulaması altında İhale Yönetimi menüsü ekler. Her ihale için ihale
numarası, adı, müşteri, tarihler, durum (Hazırlık / Teklif Verildi /
Kazanıldı / Kaybedildi / İptal), sorumlu, açıklama ve doküman ekleri
içeren bağımsız bir ihale kaydı tutulur.

İhale formundaki Teklifler smart button'u bağlı satış tekliflerini
listeler; Teklif Oluştur butonu müşteri, satış türü (İhale), ihale
bağlantısı ve sorumlu bilgileri önceden dolu standart satış teklifi
formunu açar.

sale.order modeline Satış Türü (Yurtiçi / Yurtdışı / İhale / Bedelsiz /
Diğer) ve İhale alanları eklenir. Satış Türü "İhale" olduğunda ihale
seçimi zorunludur ve yalnızca ilgili müşterinin ihaleleri seçilebilir.
Teklif revizyonlarında (copy) satış türü ve ihale bağlantısı korunur.

Bağlı teklifi bulunan ihale kayıtları silinemez. İhale Kullanıcısı
grubu salt okunur erişim, İhale Yöneticisi grubu tam yetki sağlar.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Sales/Sales',
    'version': '19.0.1.0.0',

    'depends': [
        'sale',
    ],

    'data': [
        'security/sale_tender_security.xml',
        'security/ir.model.access.csv',
        'views/sale_tender_views.xml',
        'views/sale_order_views.xml',
        'views/sale_tender_menus.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
