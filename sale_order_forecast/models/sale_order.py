# -*- coding: utf-8 -*-
from odoo import api, models, fields, _
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import format_datetime


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    order_nature = fields.Selection(
        selection=[
            ('confirmed', 'Kesin'),
            ('forecast', 'Öngörü'),
        ],
        string='Sipariş Niteliği',
        tracking=True,
        copy=False,
        help="Kesin: standart satış siparişi süreci.\n"
             "Öngörü: teslimat emri oluşturulmadan onaylanabilen satış siparişi.")
    forecast_converted = fields.Boolean(
        string='Öngörü\'den Aktarım Yapıldı',
        default=False,
        copy=False,
        readonly=True,
        help="Bu Öngörü siparişinden en az bir Kesin sipariş aktarımı "
             "yapılmıştır.")
    forecast_order_id = fields.Many2one(
        'sale.order',
        string='Kaynak Öngörü Siparişi',
        copy=False,
        readonly=True,
        index=True,
        ondelete='set null',
        help="Bu Kesin siparişin aktarıldığı Öngörü siparişi.")
    confirmed_order_ids = fields.One2many(
        'sale.order', 'forecast_order_id',
        string='Kesin Siparişler',
        copy=False,
        readonly=True,
        help="Bu Öngörü siparişinden aktarılarak oluşturulan Kesin siparişler.")
    confirmed_order_count = fields.Integer(
        string='Kesin Sipariş Sayısı',
        compute='_compute_confirmed_order_count')
    has_transferable_lines = fields.Boolean(
        string='Aktarılabilir Satır Var',
        compute='_compute_has_transferable_lines')
    was_confirmed = fields.Boolean(
        string='Daha Önce Onaylandı',
        default=False,
        copy=False,
        readonly=True,
        help="Sipariş en az bir kez onaylandı; niteliği artık değiştirilemez.")

    @api.depends('confirmed_order_ids')
    def _compute_confirmed_order_count(self):
        for order in self:
            order.confirmed_order_count = len(order.confirmed_order_ids)

    @api.depends('order_nature',
                 'order_line.display_type',
                 'order_line.product_uom_qty')
    def _compute_has_transferable_lines(self):
        for order in self:
            order.has_transferable_lines = (
                order.order_nature == 'forecast'
                and any(not l.display_type and l.product_uom_qty > 0
                        for l in order.order_line))

    def write(self, vals):
        if 'order_nature' in vals and not self.env.context.get('order_nature_change_allowed'):
            for order in self:
                if vals['order_nature'] == order.order_nature:
                    continue
                if order.was_confirmed or order.state not in ('draft', 'sent'):
                    raise UserError(_(
                        "Onaylanmış bir siparişin niteliği değiştirilemez. Öngörü "
                        "siparişleri yalnızca \"Kesin Siparişe Dönüştür\" butonu "
                        "ile Kesin niteliğe çevrilebilir."))
        return super().write(vals)

    def action_confirm(self):
        """ Sipariş niteliği seçilmemiş teklifler doğrudan onaylanmaz;
        kullanıcıya nitelik seçim penceresi açılır.

        Pencere yalnızca backend arayüzünden gelen onay çağrılarında
        açılır. Portal, online ödeme, webhook, XML-RPC veya cron gibi
        arayüz dışı onaylarda sipariş otomatik olarak Kesin niteliği
        alır. Entegrasyonlar ayrıca `order_nature` context anahtarı ile
        niteliği önden iletebilir:
        order.with_context(order_nature='forecast').action_confirm()
        """
        missing = self.filtered(
            lambda o: not o.order_nature and o.state in ('draft', 'sent'))
        if missing:
            auto_nature = self.env.context.get('order_nature')
            if auto_nature not in ('confirmed', 'forecast') \
                    and not self._is_backend_button_call():
                auto_nature = 'confirmed'
            if auto_nature in ('confirmed', 'forecast'):
                missing.with_context(order_nature_change_allowed=True).write(
                    {'order_nature': auto_nature})
                missing = self.browse()
        if missing:
            if len(missing) > 1:
                raise UserError(_(
                    "Sipariş niteliği seçilmemiş birden fazla teklif var. "
                    "Lütfen teklifleri tek tek onaylayarak niteliklerini "
                    "belirleyin."))
            return missing._action_open_nature_wizard()
        return super().action_confirm()

    def _is_backend_button_call(self):
        """Onay çağrısı backend arayüzünden mi geliyor?

        Portal, online ödeme, sağlayıcı webhook'ları, XML-RPC/JSON-RPC ve
        cron gibi arayüz dışı çağrılarda nitelik penceresi gösterilemez."""
        try:
            path = request.httprequest.path or ''
        except RuntimeError:
            return False
        return path.startswith('/web/')

    def _action_confirm(self):
        self.was_confirmed = True
        return super()._action_confirm()

    def _action_open_nature_wizard(self):
        self.ensure_one()
        wizard = self.env['sale.order.nature.wizard'].create({
            'order_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sipariş Niteliğini Seçiniz'),
            'res_model': 'sale.order.nature.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_draft(self):
        """İptal edilen sipariş teklife döndürüldüğünde sipariş niteliği
        sıfırlanır; yeniden onayda seçim penceresi tekrar sorar."""
        cancelled = self.filtered(lambda o: o.state == 'cancel')
        res = super().action_draft()
        cancelled.with_context(order_nature_change_allowed=True).write({
            'order_nature': False,
            'forecast_converted': False,
            'was_confirmed': False,
        })
        cancelled.order_line.write({
            'to_transfer': False,
            'transfer_qty': 0.0,
        })
        return res

    def action_convert_to_confirmed(self):
        """İşaretli satırları yeni bir Kesin siparişe aktarır ve onaylar.

        Öngörü siparişi yerinde kalır; aktarılan miktar satırdan düşülür,
        tamamı aktarılan satır silinir. İşlem parçalı olarak tekrar
        edilebilir."""
        new_orders = self.env['sale.order']
        for order in self:
            if order.order_nature != 'forecast':
                raise UserError(_(
                    "Yalnızca Öngörü niteliğindeki siparişlerden Kesin "
                    "siparişe aktarım yapılabilir."))
            if order.state != 'sale':
                raise UserError(_(
                    "Yalnızca onaylanmış (Satış Siparişi) Öngörü "
                    "siparişlerinden aktarım yapılabilir."))
            new_orders |= order._transfer_selected_lines()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'sale.action_orders')
        if len(new_orders) == 1:
            action.update({
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_id': new_orders.id,
            })
        else:
            action['domain'] = [('id', 'in', new_orders.ids)]
        action['context'] = dict(self.env.context)
        return action

    def _transfer_selected_lines(self):
        """İşaretli satırlardan yeni bir Kesin sipariş oluşturup onaylar.

        Tüm işlem tek transaction içinde yürür; herhangi bir adım hata
        verirse yeni sipariş dahil her şey geri alınır.
        """
        self.ensure_one()
        lines = self.order_line.filtered(
            lambda l: l.to_transfer and not l.display_type)
        if not lines:
            raise UserError(_(
                "Lütfen Kesin siparişe aktarılacak satırları işaretleyin."))
        qty_map = {}
        for line in lines:
            qty = line.transfer_qty or line.product_uom_qty
            if qty <= 0:
                raise UserError(_(
                    "\"%(product)s\" satırında aktarılabilir miktar "
                    "kalmamış.",
                    product=line.product_id.display_name))
            if qty > line.product_uom_qty:
                raise UserError(_(
                    "\"%(product)s\" satırının aktarım miktarı (%(qty)s), "
                    "sipariş miktarından (%(ordered)s) büyük olamaz.",
                    product=line.product_id.display_name,
                    qty=qty,
                    ordered=line.product_uom_qty))
            qty_map[line.id] = qty
        detail = ', '.join(
            "%s (%s)" % (l.product_id.display_name, qty_map[l.id])
            for l in lines)
        new_order = self._create_transfer_order(lines, qty_map)
        for line in lines:
            qty = qty_map[line.id]
            if qty >= line.product_uom_qty:
                # Miktarın tamamı aktarıldı: satır Öngörü siparişinden kalkar.
                line.unlink()
            else:
                line.write({
                    'product_uom_qty': line.product_uom_qty - qty,
                    'to_transfer': False,
                    'transfer_qty': 0.0,
                })
        self.forecast_converted = True
        self.message_post(body=_(
            "%(count)s satır %(name)s Kesin siparişine aktarıldı: "
            "%(detail)s. İşlemi yapan: %(user)s – Tarih: %(date)s",
            count=len(lines),
            name=new_order.name,
            detail=detail,
            user=self.env.user.display_name,
            date=format_datetime(self.env, fields.Datetime.now())))
        new_order.message_post(body=_(
            "Sipariş, %(name)s Öngörü siparişinden aktarılarak "
            "oluşturuldu. İşlemi yapan: %(user)s – Tarih: %(date)s",
            name=self.name,
            user=self.env.user.display_name,
            date=format_datetime(self.env, fields.Datetime.now())))
        return new_order

    def _create_transfer_order(self, lines, qty_map):
        """Aktarım için yeni bir Kesin satış siparişi oluşturur ve onaylar.

        Başlık bilgileri kaynak siparişten kopyalanır; yalnızca işaretli
        satırlar, aktarım miktarlarıyla yeni siparişe taşınır. Standart
        `action_confirm` çağrısı teslimat/stok süreçlerini başlatır."""
        self.ensure_one()
        order_vals = self.copy_data(default={
            'order_nature': 'confirmed',
            'forecast_order_id': self.id,
            'origin': self.name,
        })[0]
        order_vals['order_line'] = []
        # Revizyon/numara alanları kopyalanmasın; yeni sipariş kendi
        # numarasını ve revizyon yaşam döngüsünü başlatsın (base_revision
        # gibi numara+revizyon benzersizliği zorlayan modüllerle çakışmaz).
        for key in ('name', 'unrevisioned_name', 'revision_number',
                    'current_revision_id', 'old_revision_ids', 'state'):
            order_vals.pop(key, None)
        new_order = self.create(order_vals)
        for line in lines:
            line_vals = line.copy_data(default={
                'order_id': new_order.id,
                'product_uom_qty': qty_map[line.id],
                'forecast_source_line_id': line.id,
            })[0]
            self.env['sale.order.line'].create(line_vals)
        new_order.action_confirm()
        return new_order

    def action_view_confirmed_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'sale.action_orders')
        orders = self.confirmed_order_ids
        if len(orders) == 1:
            action.update({
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_id': orders.id,
            })
        else:
            action['domain'] = [('id', 'in', orders.ids)]
        action['context'] = dict(self.env.context)
        return action

    def action_view_forecast_source(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.forecast_order_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

    def _create_invoices(self, grouped=False, final=False, date=None):
        forecast_orders = self.filtered(lambda o: o.order_nature == 'forecast')
        if forecast_orders:
            raise UserError(_(
                "Öngörü niteliğindeki siparişlerden fatura oluşturulamaz. "
                "Önce siparişi Kesin niteliğe dönüştürün. (%s)",
                ', '.join(forecast_orders.mapped('name'))))
        return super()._create_invoices(grouped=grouped, final=final, date=date)
