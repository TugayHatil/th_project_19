# -*- coding: utf-8 -*-
{
    'name': "CRM İkinci Para Birimi",

    'summary': "Fırsatlara ikinci para birimi: tutar girişi, otomatik şirket para birimi çevrimi ve oranlı gelir",

    'description': """CRM fırsatlarına (crm.lead) şirket para birimine ek olarak
ikinci bir para birimi ekler.

Eklenen alanlar: Anlaşma Para Birimi (Deal Currency), Diğer Para Birimi
Geliri ve Oranlı Gelir (Diğer Para Birimi). Kullanıcı ikinci para
biriminde tutarı girdiğinde sistem, kur üzerinden şirket para birimine
göre tutarı hesaplayıp standart Beklenen Gelir alanına yazar. Oranlı
Gelir, ikinci para birimindeki tutarın olasılık oranına göre düşen
payını gösterir. İkinci para birimi tutarları kanban kartında da
görüntülenir.""",

    'author': "Projet Solutions",
    'website': "https://projet.solutions",

    'category': 'Sales/CRM',
    'version': '19.0.1.0.0',

    'depends': [
        'crm',
    ],

    'data': [
        'views/crm_lead_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
