# -*- coding: utf-8 -*-
"""Renumber existing MİP records: drop the MİP- prefix and pad to 10
digits, keeping each record's original number. The sequence itself is
aligned to the plain-digit format and continues after the highest
assigned number."""


def migrate(cr, version):
    cr.execute("SELECT id, name FROM mip_need_line ORDER BY id")
    next_no = 0
    for rec_id, name in cr.fetchall():
        digits = "".join(ch for ch in (name or "") if ch.isdigit())
        no = int(digits) if digits else next_no
        cr.execute(
            "UPDATE mip_need_line SET name = %s WHERE id = %s",
            (str(no).zfill(10), rec_id))
        next_no = max(next_no, no + 1)
    cr.execute(
        "UPDATE ir_sequence SET prefix = NULL, padding = 10, "
        "number_next_actual = %s WHERE code = 'mip.need.line'",
        (next_no,))
