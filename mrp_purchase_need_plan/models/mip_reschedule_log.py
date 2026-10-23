# -*- coding: utf-8 -*-
from odoo import fields, models


class MipRescheduleLog(models.Model):
    """Audit trail of planned-date changes on need moves.

    One row is minted by the stock.move write hook every time a move's
    plan-relevant date changes (date for manufacturing components,
    date_deadline for deliveries). The plan's "İstisna" column links to
    this history — a fixed label, not a master record, since the
    exception vocabulary stays intentionally small.
    """
    _name = "mip.reschedule.log"
    _description = "MİP Termin Değişiklik Geçmişi"
    _order = "change_date, id"

    key = fields.Char(index=True)
    move_id = fields.Many2one(
        "stock.move", index=True, ondelete="cascade", readonly=True)
    doc_name = fields.Char(string="Kayıt No", readonly=True)
    user_id = fields.Many2one(
        "res.users", string="Değiştiren", readonly=True)
    change_date = fields.Datetime(
        string="Değişiklik Tarihi", readonly=True)
    planned_date = fields.Date(string="Planlanan Tarih", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
