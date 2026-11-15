# -*- coding: utf-8 -*-
from odoo import models


class QualityCheckWizard(models.TransientModel):
    _inherit = 'quality.check.wizard'

    def confirm_fail(self):
        # The internal fail path (and the auto pass for the good part)
        # must not reopen the dialog or hit the send guard.
        self = self.with_context(pqn_internal=True)
        return super().confirm_fail()
