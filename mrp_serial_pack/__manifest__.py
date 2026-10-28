# -*- coding: utf-8 -*-
{
    'name': "MRP Serial Pack - Auto Box & Pallet",

    'summary': "Seri numaralı üretimde Veri Al butonu ile otomatik seri, koli (BOX) ve palet (PAL) oluşturma",

    'description': """Seri numarasıyla takip edilen ürünlerin üretim emirleri üzerinden
paketlenmesini otomatikleştirir.

Üretim emri formundaki "Aktarılacak Miktar" alanı ve "Veri Al" butonu ile:

- Hedef miktar kadar seri numarası Odoo'nun standart lot/serial yapısıyla hazırlanır.
- Her 5 seri için bir koli (BOX0000000001...), her 10 koli için bir palet
  (PAL0000000001...) otomatik oluşturulur ve numaralandırılır.
- Seri numaraları üretim hareket satırları üzerinden kolilere, koliler
  paket hiyerarşisi (package_dest_id) üzerinden paletlere bağlanır.
- Tekrarlanan çalıştırmalarda mevcut kayıtlar korunur, yalnızca eksik
  miktar kadar yeni seri/paket hazırlanır.
- İşlem üretim emrini tamamlamaz; stokta mevcut hale getirmez. Standart
  "Produce / Produce All" akışı ile üretim tamamlandığında koli->palet
  bağlantısı gerçek paket hiyerarşisine dönüşür.

Veri kaynağı (seri numarası üretimi) paketleme iş kurallarından ayrı
tutulmuştur; ileride SQL ara görünümü entegre edildiğinde yalnızca
`_prepare_serial_lots` veri kaynağı değişecektir.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Manufacturing/Manufacturing',
    'version': '19.0.1.0.0',

    'depends': [
        'mrp',
    ],

    'data': [
        'data/mrp_serial_pack_data.xml',
        'views/mrp_production_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
}
