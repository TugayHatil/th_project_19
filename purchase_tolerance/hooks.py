# -*- coding: utf-8 -*-


def post_init_hook(env):
    """Mevcut ürünlere varsayılan satınalma toleransını uygula.

    Modül kurulmadan önce oluşturulmuş ürünlerde tolerans alanı boş (0)
    kalacağından tüm fazla teslimatlar engellenirdi. Kurulum sırasında
    genel ayardaki varsayılan değer mevcut ürünlere yazılır; sonradan
    ürün bazında değiştirilebilir.
    """
    param = env['ir.config_parameter'].sudo().get_param(
        'purchase_tolerance.default_purchase_tolerance')
    env.cr.execute(
        "UPDATE product_template SET purchase_tolerance = %s "
        "WHERE purchase_tolerance IS NULL OR purchase_tolerance = 0",
        (float(param or 0.0),))
