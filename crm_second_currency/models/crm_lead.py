# -*- coding: utf-8 -*-

from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    currency_id = fields.Many2one(
        'res.currency',
        string='Deal Currency',
        default=lambda self: self.env.company.currency_id,
    )
    planned_revenue_second = fields.Monetary(
        string='Revenue Other Currency',
        currency_field='currency_id',
        tracking=True,
    )
    prorated_revenue_second = fields.Monetary(
        string='Prorated Revenue (Other Currency)',
        currency_field='currency_id',
        compute='_compute_prorated_revenue_second',
    )

    @api.depends('planned_revenue_second', 'probability')
    def _compute_prorated_revenue_second(self):
        for lead in self:
            lead.prorated_revenue_second = lead.planned_revenue_second * (lead.probability / 100.0)

    @api.onchange('currency_id', 'planned_revenue_second')
    def _onchange_planned_revenue_second(self):
        """Mirror the amount quoted in the customer's currency into the
        company-currency ``expected_revenue`` so that probability weighting
        and pipeline reporting stay consistent.
        """
        if not self.currency_id:
            return
        company = self.company_id or self.env.company
        self.expected_revenue = self.currency_id._convert(
            self.planned_revenue_second,
            company.currency_id,
            company,
            self.create_date or fields.Date.context_today(self),
        )
