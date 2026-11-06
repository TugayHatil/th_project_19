# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Selection değeri 'normal', 'confirmed' olarak yeniden adlandırıldı.
    Varsayılan değer de kaldırıldığından eski 'normal' kayıtları 'confirmed'
    değerine taşınır."""
    cr.execute("""
        UPDATE sale_order
        SET order_nature = 'confirmed'
        WHERE order_nature = 'normal'
    """)
