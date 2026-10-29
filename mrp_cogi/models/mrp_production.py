# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.tools import float_is_zero


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    cogi_ids = fields.One2many('mrp.cogi.record', 'production_id',
                               string='COGI Kayıtları')
    cogi_count = fields.Integer(compute='_compute_cogi_count')

    @api.depends('cogi_ids')
    def _compute_cogi_count(self):
        for production in self:
            production.cogi_count = len(production.cogi_ids)

    def _post_inventory(self, cancel_backorder=False):
        self._cogi_cap_consumption_to_available()
        res = super()._post_inventory(cancel_backorder=cancel_backorder)
        self._create_cogi_records()
        return res

    def _cogi_cap_consumption_to_available(self):
        """Reçete bileşen hareket satırlarının miktarını, kaynak konumdaki
        fiziksel stoğun karşılayabileceği kadara indirir.

        _action_done her satırın miktarını tek quant'tan düşer; stok
        yetersizse quant negatife gider ve üretim emri bloklanır. Bu metot
        stoğu olmayan kısmı satırlardan düşürür; fark _create_cogi_records
        tarafından COGI kaydına dönüştürülür."""
        Quant = self.env['stock.quant']
        for production in self:
            for move in production.move_raw_ids:
                if not (move.bom_line_id and move.picked
                        and move.state not in ('done', 'cancel')):
                    continue
                product = move.product_id
                if not product.is_storable or move._should_bypass_reservation():
                    continue
                product_uom = product.uom_id
                budgets = {}
                for line in move.move_line_ids.filtered(
                        lambda l: l.picked and l.quantity > 0):
                    qty = line.product_uom_id._compute_quantity(
                        line.quantity, product_uom)
                    if product_uom.compare(qty, 0) <= 0:
                        continue
                    if product.tracking != 'none' and not line.lot_id:
                        # Takip edilen üründe lotsuz satır stoktan düşemez.
                        allowed = 0.0
                        key = ('nolot', line.package_id.id, line.owner_id.id)
                    else:
                        key = (line.lot_id.id, line.package_id.id,
                               line.owner_id.id)
                        if key not in budgets:
                            quant = Quant._gather(
                                product, move.location_id,
                                lot_id=line.lot_id or None,
                                package_id=line.package_id or None,
                                owner_id=line.owner_id or None,
                                strict=True)[:1]
                            budgets[key] = quant.quantity if quant else 0.0
                        allowed = budgets[key]
                    take = min(qty, max(allowed, 0.0))
                    budgets[key] = allowed - take
                    if product_uom.compare(take, qty) < 0:
                        line.quantity = line.product_uom_id._compute_quantity(
                            take, line.product_uom_id)
        return True

    def _create_cogi_records(self):
        """Tamamlanan üretim emrinde reçete bileşenlerinin planlanan ve
        tüketilen miktarlarını karşılaştırır; fark için COGI kaydı açar.
        Yalnızca reçeteden gelen hareketler (bom_line_id) değerlendirilir."""
        Cogi = self.env['mrp.cogi.record']
        for production in self:
            created = Cogi
            for move in production.move_raw_ids.filtered(
                    lambda m: m.bom_line_id and m.state != 'draft'):
                if move.source_cogi_ids:
                    continue
                product_uom = move.product_id.uom_id
                planned = move.product_uom._compute_quantity(
                    move.product_uom_qty, product_uom)
                consumed = move.product_uom._compute_quantity(
                    move.quantity, product_uom)
                missing = product_uom.round(planned - consumed)
                if float_is_zero(missing, precision_rounding=product_uom.rounding) \
                        or missing <= 0:
                    continue
                error = _(
                    'Bileşen için planlanan %(planned)s %(uom)s tüketimin '
                    '%(missing)s %(uom)s kadarı gerçekleştirilemedi.',
                    planned=planned, uom=product_uom.display_name, missing=missing)
                created |= Cogi.create({
                    'company_id': production.company_id.id,
                    'production_id': production.id,
                    'production_name': production.name,
                    'finished_product_id': production.product_id.id,
                    'product_id': move.product_id.id,
                    'component_name': move.product_id.display_name,
                    'source_move_id': move.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'product_uom_id': product_uom.id,
                    'planned_qty': planned,
                    'consumed_qty': consumed,
                    'initial_missing_qty': missing,
                    'operator_id': self.env.user.id,
                    'error_message': error,
                    'original_error_message': error,
                })
            if created:
                production._send_cogi_notification(created)
        return True

    def _send_cogi_notification(self, cogi_records):
        """Yeni COGI kayıtlarını mail şablonuyla chatter'a yazar ve
        sorumlu kullanıcıya e-posta bildirimi gönderir. Gönderilen
        içerik chatter'da da görünür."""
        self.ensure_one()
        template = self.env.ref('mrp_cogi.email_template_cogi_notification',
                                raise_if_not_found=False)
        if template:
            body = template._render_template(
                'body_html', 'mrp.production', self.id)[self.id]
            subject = template._render_template(
                'subject', 'mrp.production', self.id)[self.id]
        else:
            lines = ', '.join(
                '%s (%s: %s %s)' % (
                    c.name, c.component_name or '',
                    c.initial_missing_qty,
                    c.product_uom_id.display_name)
                for c in cogi_records)
            body = _('%(count)s COGI kaydı oluşturuldu: %(lines)s',
                     count=len(cogi_records), lines=lines)
            subject = _('COGI Bildirimi')
        partners = (self.user_id.partner_id
                    | cogi_records.responsible_id.partner_id).filtered('email')
        self.message_post(
            body=body,
            subject=subject,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=partners.ids,
            email_layout_xmlid='mail.mail_notification_light',
        )

    def action_view_cogi_records(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('mrp_cogi.mrp_cogi_record_action')
        action['domain'] = [('production_id', '=', self.id)]
        action['context'] = {'default_production_id': self.id, 'create': 0}
        if self.cogi_count == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = self.cogi_ids.id
        return action
