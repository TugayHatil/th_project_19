# -*- coding: utf-8 -*-
from odoo import fields, models


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    noticed_location_id = fields.Many2one(
        'luna.noticed.location', string='Farkedildiği Yer')
    noticed_date = fields.Date(string='Farketme Zamanı')
    hardware_version_id = fields.Many2one(
        'luna.hardware.version', string='Donanım Versiyonu')
    software_version_id = fields.Many2one(
        'luna.software.version', string='Yazılım Versiyonu')
    serial_number = fields.Char(string='Seri Numarası')
    luna_product_id = fields.Many2one(
        'product.product', string='Ürün')

    complaint_detail = fields.Html(string='Şikayet Detayı')
    environment_conditions = fields.Html(string='Nerede / Ortam Koşulları')
    impact = fields.Html(
        string='Etki', help='Kaç cihaz, kaç müşteri vb.')
    reproduction_steps = fields.Html(string='Sorunu Tekrarlama Adımları')
    classification = fields.Html(
        string='Sınıflandırma', help='Donanım, yazılım, üretim, kalite')
    temporary_action = fields.Html(string='Geçici Aksiyon')
    root_cause = fields.Html(string='Kök Neden')
    permanent_solution = fields.Html(string='Kalıcı Çözüm')
    validation = fields.Html(string='Doğrulama')
    preventive_action_plan = fields.Html(string='Önleyici Aksiyon Planı')
    other_products_impact = fields.Html(
        string='Diğer Ürünlere Etkisi Olabilir mi?')
