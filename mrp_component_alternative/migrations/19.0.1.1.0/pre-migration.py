# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Remove the passive placeholder lines created by the previous
    version. Component moves are now repurposed for the allocation
    itself, so no zero-demand origin row is needed anymore."""
    cr.execute("""
        SELECT id FROM stock_move
        WHERE is_alternative_origin AND state = 'cancel'
    """)
    ids = [row[0] for row in cr.fetchall()]
    if not ids:
        return
    cr.execute(
        "DELETE FROM stock_move_line WHERE move_id = ANY(%s)", (ids,))
    cr.execute(
        "DELETE FROM stock_move WHERE id = ANY(%s)", (ids,))
