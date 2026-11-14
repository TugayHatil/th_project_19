# -*- coding: utf-8 -*-
from odoo import models


class QualityCheckWizard(models.TransientModel):
    _inherit = 'quality.check.wizard'

    # The wizard / failure dialog write the line quantity themselves
    # (qty_tested / qty_failed); those are internal quality-flow writes,
    # not user edits, so they bypass the approval cap.
    def _qc_gate_off(self):
        return self.with_context(qc_gate_off=True)

    def do_pass(self):
        return super(QualityCheckWizard, self._qc_gate_off()).do_pass()

    def do_fail(self):
        return super(QualityCheckWizard, self._qc_gate_off()).do_fail()

    def do_measure(self):
        return super(QualityCheckWizard, self._qc_gate_off()).do_measure()

    def confirm_fail(self):
        return super(QualityCheckWizard, self._qc_gate_off()).confirm_fail()

    def confirm_measure(self):
        return super(QualityCheckWizard, self._qc_gate_off()).confirm_measure()

    def correct_measure(self):
        return super(QualityCheckWizard, self._qc_gate_off()).correct_measure()
