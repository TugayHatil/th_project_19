# -*- coding: utf-8 -*-
from . import models
from . import wizard


def _post_init_cogi(env):
    # Modül kurulumunda mevcut hareketlerin sıralama anahtarını doldur.
    env.cr.execute(
        "UPDATE stock_move SET cogi_sort_key = COALESCE(cogi_source_move_id, id) "
        "WHERE cogi_sort_key IS NULL")
