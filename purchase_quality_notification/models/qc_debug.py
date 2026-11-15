# -*- coding: utf-8 -*-
# TEMPORARY DEBUG INSTRUMENTATION — remove before release.
import json
from odoo import models


def _qclog(env, msg):
    env['ir.logging'].create({
        'name': 'QCDEBUG', 'type': 'server', 'dbname': env.cr.dbname,
        'level': 'INFO', 'message': msg, 'path': 'qc', 'func': 'x',
        'line': '0'})


def _ctx(env):
    c = env.context
    return {k: c.get(k) for k in
            ('qc_gate_off', 'qc_internal', 'qc_user_pass', 'qc_in_confirm',
             'from_failure_form') if k in c}


class StockMoveDebug(models.Model):
    _inherit = 'stock.move'

    def _do_unreserve(self):
        _qclog(self.env, 'unreserve %s ctx=%s' % (self.ids, _ctx(self.env)))
        return super()._do_unreserve()

    def _split(self, qty, restrict_partner_id=False):
        _qclog(self.env, 'move._split ids=%s qty=%s ctx=%s' % (
            self.ids, qty, _ctx(self.env)))
        res = super()._split(qty, restrict_partner_id=restrict_partner_id)
        _qclog(self.env, 'move._split res=%s' % (res,))
        return res

    def write(self, vals):
        if any(k in vals for k in ('product_uom_qty', 'state', 'location_dest_id')):
            _qclog(self.env, 'move.write ids=%s vals=%s ctx=%s' % (
                self.ids, vals, _ctx(self.env)))
        return super().write(vals)

    def _action_assign(self, force_qty=False):
        _qclog(self.env, 'move._action_assign ids=%s ctx=%s' % (
            self.ids, _ctx(self.env)))
        return super()._action_assign(force_qty=force_qty)


class StockMoveLineDebug(models.Model):
    _inherit = 'stock.move.line'

    def write(self, vals):
        if 'quantity' in vals:
            _qclog(self.env, 'ml.write ids=%s q=%s ctx=%s' % (
                self.ids, vals.get('quantity'), _ctx(self.env)))
        return super().write(vals)

    def _split(self, qty=None, **kwargs):
        _qclog(self.env, 'ml._split ids=%s qty=%s ctx=%s' % (
            self.ids, qty, _ctx(self.env)))
        return super()._split(qty=qty, **kwargs)

    def unlink(self):
        _qclog(self.env, 'ml.unlink ids=%s ctx=%s' % (
            self.ids, _ctx(self.env)))
        return super().unlink()


class QualityCheckDebug(models.Model):
    _inherit = 'quality.check'

    def write(self, vals):
        _qclog(self.env, 'check.write ids=%s vals=%s ctx=%s' % (
            self.ids, vals, _ctx(self.env)))
        return super().write(vals)
