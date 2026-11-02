# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mrp_alternative_partial = fields.Boolean(
        string="Alternatif Bileşenlerde Parçalı Kullanım",
        config_parameter="mrp_component_alternative.allow_partial_usage")
