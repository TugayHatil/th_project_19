# -*- coding: utf-8 -*-
from odoo import models


class QualityCheckWizard(models.TransientModel):
    _inherit = 'quality.check.wizard'

    def confirm_fail(self):
        # The internal fail path must not reopen the dialog.
        self = self.with_context(pqn_skip_fail_dialog=True)
        return super().confirm_fail()
