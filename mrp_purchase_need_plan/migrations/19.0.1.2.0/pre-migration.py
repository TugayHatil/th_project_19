# -*- coding: utf-8 -*-
"""Add and populate mip_need_line.key BEFORE the ORM creates it as a
required column: existing move-backed records get the "mv:<id>" key so
the NOT NULL / unique enforcement has valid data on upgrade."""


def migrate(cr, version):
    cr.execute(
        "ALTER TABLE mip_need_line "
        "ADD COLUMN IF NOT EXISTS key varchar")
    cr.execute(
        "UPDATE mip_need_line SET key = 'mv:' || move_id "
        "WHERE key IS NULL AND move_id IS NOT NULL")
    cr.execute(
        "ALTER TABLE mip_need_line "
        "ALTER COLUMN key SET NOT NULL")
