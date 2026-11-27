# -*- coding: utf-8 -*-


def post_init_hook(env):
    """Mevcut tedarikçi fiyat satırlarına eksik sevk süresi satırlarını ekle.

    Modül kurulmadan önce oluşturulmuş tedarikçi fiyat listelerinde sevk
    süresi tablosu boş olacağından, kurulum sırasında dört sevk türünün
    satırları (süresi 0 gün) eklenir; kullanıcı günleri sonradan doldurur.
    """
    env['product.supplierinfo'].search([])._ensure_shipping_delay_lines()
