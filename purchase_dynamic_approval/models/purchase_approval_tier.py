# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PurchaseApprovalTier(models.Model):
    _name = 'purchase.approval.tier'
    _description = 'Satınalma Onay Baremı'
    _order = 'sequence, amount_min, id'
    _check_company_auto = True

    sequence = fields.Integer(string='Sıra', default=10)
    approval_flow = fields.Selection([
        ('direct', 'Direkt Alım'),
        ('indirect', 'Endirekt Alım'),
    ], string='Onay Akışı', required=True, default='direct', index=True,
        help="Bu baremin ait olduğu onay akışı. Siparişin satınalma "
             "grubuna göre ilgili akışın baremleri uygulanır.")
    amount_min = fields.Monetary(
        string='Alt Tutar', required=True, default=0.0,
        currency_field='currency_id',
        help="Baremin geçerli olduğu alt tutar sınırı (dahil).")
    amount_max = fields.Monetary(
        string='Üst Tutar', currency_field='currency_id',
        help="Baremin geçerli olduğu üst tutar sınırı (hariç). "
             "Sınırsız işaretliyse dikkate alınmaz.")
    unlimited = fields.Boolean(
        string='Sınırsız', default=False,
        help="İşaretliyse üst tutar sınırı uygulanmaz; alt tutar ve "
             "üzerindeki tüm tutarlar bu bareme girer.")
    approval_group_id = fields.Many2one(
        'res.groups', string='Onaylayıcı Grup', required=True, index=True,
        help="Bu tutar aralığına giren satınalma siparişlerini "
             "onaylama yetkisine sahip kullanıcı grubu.")
    delegate_user_id = fields.Many2one(
        'res.users', string='Vekil Onaycı',
        help="Onay grubu üyesi olmadan bu barem için onay/red yetkisi "
             "verilen alternatif kullanıcı. Onay grubu üyesi bir "
             "kullanıcı vekil olarak atanamaz.")
    active = fields.Boolean(string='Aktif', default=True)
    company_id = fields.Many2one(
        'res.company', string='Şirket', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
        store=True, readonly=True)

    @api.depends('amount_min', 'amount_max', 'unlimited', 'currency_id',
                 'approval_flow')
    def _compute_display_name(self):
        flow_labels = dict(
            self._fields['approval_flow']._description_selection(self.env))
        for tier in self:
            fmt = tier.currency_id.format if tier.currency_id \
                else lambda v: '%.2f' % v
            name = (
                _('%s ve üzeri', fmt(tier.amount_min))
                if tier.unlimited
                else _('%s – %s', fmt(tier.amount_min), fmt(tier.amount_max)))
            tier.display_name = _('%s (%s)', name,
                                  flow_labels.get(tier.approval_flow) or '')

    def _upper_bound(self):
        self.ensure_one()
        return float('inf') if self.unlimited else self.amount_max

    @api.constrains('approval_group_id', 'delegate_user_id')
    def _check_delegate_user(self):
        for tier in self:
            user = tier.delegate_user_id
            if not user:
                continue
            if user.share:
                raise ValidationError(_(
                    'Vekil Onaycı yalnızca dahili (internal) bir '
                    'kullanıcı olabilir.'))
            if user in tier.approval_group_id.all_user_ids:
                raise ValidationError(_(
                    'Vekil Onaycı olarak seçilen kullanıcı, ilgili onay '
                    'grubunun üyesidir. Onay grubu üyesi bir kullanıcı '
                    'vekil olarak atanamaz.'))

    @api.onchange('unlimited')
    def _onchange_unlimited(self):
        if self.unlimited:
            self.amount_max = 0.0

    @api.constrains('amount_min', 'amount_max', 'unlimited', 'active',
                    'company_id', 'approval_flow')
    def _check_amount_ranges(self):
        for tier in self:
            if tier.amount_min < 0:
                raise ValidationError(_('Alt tutar negatif olamaz.'))
            if not tier.unlimited and tier.amount_max <= tier.amount_min:
                raise ValidationError(_(
                    'Üst tutar, alt tutardan büyük olmalıdır.'))
        for company, flow in {
                (t.company_id, t.approval_flow) for t in self}:
            tiers = self.search([
                ('company_id', '=', company.id),
                ('approval_flow', '=', flow),
                ('active', '=', True),
            ]).sorted('amount_min')
            previous = self.browse()
            for tier in tiers:
                if previous and tier.amount_min < previous._upper_bound():
                    raise ValidationError(_(
                        'Tanımlanan tutar aralıkları birbiriyle '
                        'çakışmaktadır.'))
                previous = tier

    @api.model
    def _find_for_amount(self, company, amount, flow):
        """Alt sınır dahil, üst sınır hariç mantığıyla tutara denk gelen
        aktif baremi verilen onay akışı içinde döndürür. Aralıklar
        çakışmadığı için en fazla tek kayıt eşleşir."""
        tiers = self.search([
            ('company_id', '=', company.id),
            ('approval_flow', '=', flow),
            ('active', '=', True),
            ('amount_min', '<=', amount),
        ])
        for tier in tiers.sorted('amount_min', reverse=True):
            if tier.unlimited or amount < tier.amount_max:
                return tier
        return self.browse()
