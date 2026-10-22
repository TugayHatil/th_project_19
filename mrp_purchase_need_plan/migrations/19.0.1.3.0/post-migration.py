# -*- coding: utf-8 -*-
"""Indexes on the custom M2M traceability tables.

Domains like ``("need_move_ids", "in", ids)`` resolve through these
relation tables; without an index on the foreign column every dedup /
pending-document lookup degrades into a sequential scan — that becomes
the dominant query cost once hundreds of request lines exist."""


def migrate(cr, version):
    cr.execute(
        "CREATE INDEX IF NOT EXISTS purchase_request_line_need_move_rel_move "
        "ON purchase_request_line_need_move_rel (move_id, "
        "purchase_request_line_id)")
    cr.execute(
        "CREATE INDEX IF NOT EXISTS purchase_request_line_need_mip_rel_mip "
        "ON purchase_request_line_need_mip_rel (mip_id, "
        "purchase_request_line_id)")
