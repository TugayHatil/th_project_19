# -*- coding: utf-8 -*-
from odoo import models


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    def write(self, vals):
        res = super().write(vals)
        if vals.get('quality_state') == 'pass':
            for check in self:
                line = check.move_line_id
                if (line and line.state not in ('done', 'cancel')
                        and line._is_quality_controlled_receipt_line()):
                    line.quantity += check.qty_tested or check.qty_to_test
        return res
