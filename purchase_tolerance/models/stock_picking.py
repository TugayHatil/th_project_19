# -*- coding: utf-8 -*-
from odoo import _, Command, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_round


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    tolerance_request_ids = fields.One2many(
        'purchase.tolerance.request', 'picking_id',
        string='Tolerans Talepleri')
    tolerance_request_count = fields.Integer(
        string='Tolerans Talebi Sayısı',
        compute='_compute_tolerance_request_count', compute_sudo=True)
    tolerance_origin_picking_id = fields.Many2one(
        'stock.picking', string='Kaynak Mal Kabul', readonly=True, copy=False,
        help="Bu iade transferinin oluşturulduğu mal kabul.")
    tolerance_return_ids = fields.One2many(
        'stock.picking', 'tolerance_origin_picking_id',
        string='Tolerans İade Transferleri')
    tolerance_return_count = fields.Integer(
        string='İade Transferi Sayısı',
        compute='_compute_tolerance_request_count', compute_sudo=True)

    def _compute_tolerance_request_count(self):
        Request = self.env['purchase.tolerance.request'].sudo()
        counts = {
            picking.id: count
            for picking, count in Request._read_group(
                [('picking_id', 'in', self.ids)],
                groupby=['picking_id'], aggregates=['__count'])
        }
        Picking = self.env['stock.picking'].sudo()
        ret_counts = {
            picking.id: count
            for picking, count in Picking._read_group(
                [('tolerance_origin_picking_id', 'in', self.ids)],
                groupby=['tolerance_origin_picking_id'],
                aggregates=['__count'])
        }
        for picking in self:
            picking.tolerance_request_count = counts.get(picking.id, 0)
            picking.tolerance_return_count = ret_counts.get(picking.id, 0)

    def action_view_tolerance_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'purchase_tolerance.action_purchase_tolerance_request')
        action['domain'] = [('picking_id', '=', self.id)]
        action['context'] = dict(
            self.env.context, default_picking_id=self.id)
        return action

    def action_view_tolerance_returns(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'stock.action_picking_tree_all')
        action['domain'] = [('tolerance_origin_picking_id', '=', self.id)]
        action['context'] = dict(
            self.env.context,
            default_tolerance_origin_picking_id=self.id)
        if self.tolerance_return_count == 1:
            action.update({
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_id': self.tolerance_return_ids.id,
            })
        return action

    def _get_tolerance_excess_location(self):
        location_id = self.env['res.config.settings'].sudo() \
            ._get_excess_location_param()
        location = self.env['stock.location'].sudo().browse(
            location_id) if location_id else self.env['stock.location']
        if not location.exists() or location.usage != 'internal':
            raise UserError(_(
                'Tolerans dışı miktarın yönlendirileceği konum tanımlanmamış. '
                'Lütfen Envanter → Yapılandırma → Ayarlar altından '
                '"Tolerans Dışı Miktar Konumu" seçiniz.'))
        return location

    def _get_tolerance_moves(self):
        """Tolerans kontrolüne giren satınalma hareketlerini döner."""
        return self.move_ids.filtered(
            lambda m: m.purchase_line_id
            and m.state not in ('done', 'cancel')
            and not m.is_tolerance_excess_move
            and m._should_count_for_quantity_received())

    def _get_conditional_tolerance_requests(self, order_lines):
        """Bu transfer(ler)e bağlı koşullu onaylı talepleri
        {order_line_id: request} olarak döner (tek sorgu, son talep öncelikli)."""
        if not self or not order_lines:
            return {}
        requests = self.env['purchase.tolerance.request'].sudo().search([
            ('order_line_id', 'in', order_lines.ids),
            ('state', '=', 'conditional'),
            ('picking_id', 'in', self.ids),
        ], order='id desc')
        result = {}
        for request in requests:
            result.setdefault(request.order_line_id.id, request)
        return result

    def _get_purchase_tolerance_exceeded_lines(self):
        """Doğrulama sonrasında satınalma toleransını aşacak PO satırlarını döner.

        İade hareketleri (tedarikçiye giden) ve satınalma ile ilişkisi olmayan
        iç hareketler `_should_count_for_quantity_received` sayesinde hariç
        tutulur. Önceki kısmi teslimatlar `qty_received` üzerinden hesaba katılır.
        Tolerans dışı konuma yönlendirilen hareketler ve koşullu onaylı
        satırlar aşım sayılmaz.
        """
        aggregated = {}
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue
            moves = picking._get_tolerance_moves()
            if any(m.picked for m in moves):
                moves = moves.filtered(lambda m: m.picked)
            for move in moves:
                line = move.purchase_line_id
                qty = move.product_uom._compute_quantity(
                    move.quantity, line.product_uom_id,
                    rounding_method='HALF-UP')
                if line.product_uom_id.compare(qty, 0) <= 0:
                    continue
                data = aggregated.setdefault(line.id, {
                    'order_line': line,
                    'pickings': self.env['stock.picking'].browse(),
                    'incoming_qty': 0.0,
                })
                data['pickings'] |= picking
                data['incoming_qty'] += qty

        cond_requests = self._get_conditional_tolerance_requests(
            self.env['purchase.order.line'].browse(aggregated.keys()))
        exceeded = []
        for data in aggregated.values():
            line = data['order_line']
            projected = line.qty_received + data['incoming_qty']
            max_qty = line.product_qty * (1 + line.purchase_tolerance / 100.0)
            if float_compare(projected, max_qty,
                             precision_rounding=line.product_uom_id.rounding) <= 0:
                continue
            if data['order_line'].id in cond_requests:
                continue
            if line.product_qty:
                required = float_round(
                    max((projected / line.product_qty - 1) * 100.0, 0.0),
                    2, rounding_method='UP')
            else:
                required = 100.0
            exceeded.append({
                'picking': data['pickings'][0],
                'order_line': line,
                'ordered_qty': line.product_qty,
                'received_qty': line.qty_received,
                'incoming_qty': data['incoming_qty'],
                'current_tolerance': line.purchase_tolerance,
                'max_accepted_qty': max_qty,
                'requested_tolerance': required,
            })
        return exceeded

    def _apply_conditional_tolerance_split(self):
        """Koşullu onaylı satırlarda onaylı kısmı normal konuma, fazlayı
        tolerans dışı konuma yönlendirecek şekilde miktarı böler.

        Bölünen fiili tolerans dışı miktarı talebe bağlı iade transferinin
        miktarına senkronlar; fiili fazla kalmazsa iade iptal edilir.
        """
        moves_by_picking = {}
        order_lines = self.env['purchase.order.line']
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue
            moves = picking._get_tolerance_moves()
            if moves:
                moves_by_picking[picking.id] = moves
                order_lines |= moves.purchase_line_id
        cond_requests = self._get_conditional_tolerance_requests(order_lines)
        if not cond_requests:
            return

        excess_loc = self._get_tolerance_excess_location()
        Move = self.env['stock.move']
        actual_excess = {}  # request_id -> fiili fazla (PO satırı birimi)
        for picking in self:
            if picking.id not in moves_by_picking:
                continue
            caps = {}
            for move in moves_by_picking[picking.id].sorted('id'):
                line = move.purchase_line_id
                request = cond_requests.get(line.id)
                if not request:
                    continue
                if line.id not in caps:
                    max_qty = line.product_qty * (
                        1 + line.purchase_tolerance / 100.0)
                    caps[line.id] = max(max_qty - line.qty_received, 0.0)
                qty = move.product_uom._compute_quantity(
                    move.quantity, line.product_uom_id,
                    rounding_method='HALF-UP')
                if line.product_uom_id.compare(qty, 0) <= 0:
                    continue
                allowed = min(qty, caps[line.id])
                caps[line.id] -= allowed
                excess_qty = qty - allowed
                if float_compare(
                        excess_qty, 0.0,
                        precision_rounding=line.product_uom_id.rounding) <= 0:
                    continue
                actual_excess[request.id] = \
                    actual_excess.get(request.id, 0.0) + excess_qty
                allowed_move_qty = line.product_uom_id._compute_quantity(
                    allowed, move.product_uom, rounding_method='HALF-UP')
                if move.product_uom.compare(allowed_move_qty, 0) <= 0:
                    # Hareketin tamamı tolerans dışı: aynı hareketi tolerans
                    # dışı konuma yönlendir (iptal satır bırakmaz).
                    move.write({
                        'location_dest_id': excess_loc.id,
                        'is_tolerance_excess_move': True,
                    })
                    continue
                excess_move_qty = move.quantity - allowed_move_qty
                move.write({'quantity': allowed_move_qty, 'picked': True})
                excess_move = Move.create({
                    'name': move.product_id.display_name,
                    'product_id': move.product_id.id,
                    'product_uom_qty': excess_move_qty,
                    'product_uom': move.product_uom.id,
                    'picking_id': picking.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': excess_loc.id,
                    'purchase_line_id': line.id,
                    'is_tolerance_excess_move': True,
                    'company_id': picking.company_id.id,
                    'partner_id': picking.partner_id.id,
                })
                excess_move._action_confirm(merge=False)
                excess_move.write({
                    'quantity': excess_move_qty,
                    'picked': True,
                })
                request.sudo().move_ids = [Command.link(excess_move.id)]

        # Fiili fazlalığı iade transferlerinin miktarıyla senkronla;
        # fazla hiç kalmadıysa iade iptal edilir.
        Request = self.env['purchase.tolerance.request'].sudo()
        for request in Request.browse(
                {r.id for r in cond_requests.values()}):
            return_picking = request.return_picking_id
            if not return_picking \
                    or return_picking.state in ('done', 'cancel'):
                continue
            excess_qty = actual_excess.get(request.id, 0.0)
            if float_compare(excess_qty, 0.0, precision_digits=2) <= 0:
                return_picking.action_cancel()
                return_picking.message_post(body=_(
                    'Fiili girişte tolerans dışı miktar kalmadığı için bu '
                    'iade transferi iptal edildi.'))
            else:
                for move in return_picking.move_ids.filtered(
                        lambda m: m.state not in ('done', 'cancel')):
                    move.write({
                        'product_uom_qty': excess_qty,
                        'quantity': excess_qty,
                    })

    def button_validate(self):
        if not self.env.context.get('skip_purchase_tolerance_check'):
            exceeded = self._get_purchase_tolerance_exceeded_lines()
            if exceeded:
                wizard = self.env['purchase.tolerance.request.wizard'] \
                    .create_from_exceeded(self, exceeded)
                return wizard._get_open_action()
            self._apply_conditional_tolerance_split()
        # _action_done aynı çağrı zincirinde tekrar kontrol yapmasın;
        # farklı istekten gelen _action_done çağrıları (ör. iade
        # sihirbazı process()) kendi kontrolünü yapar.
        return super(StockPicking, self.with_context(
            skip_purchase_tolerance_check=True)).button_validate()

    def _get_exceeded_tolerance_message(self, exceeded):
        message = _(
            'Satınalma toleransı aşıldığı için mal kabul doğrulanamadı:')
        for data in exceeded:
            line = data['order_line']
            message += _(
                '\n• %(product)s — sipariş: %(ordered)s %(uom)s, '
                'mevcut tolerans: %(tol)s%%, maks. kabul: %(max)s %(uom)s, '
                'toplam kabul edilecek: %(total)s %(uom)s',
                product=line.product_id.display_name,
                ordered=data['ordered_qty'],
                uom=line.product_uom_id.name,
                tol=data['current_tolerance'],
                max=data['max_accepted_qty'],
                total=data['received_qty'] + data['incoming_qty'],
            )
        message += _(
            '\n\nTransfer ekranından "Doğrula" ile tolerans aşımı '
            'talebi oluşturabilirsiniz.')
        return message

    def _action_done(self):
        if not self.env.context.get('skip_purchase_tolerance_check'):
            exceeded = self._get_purchase_tolerance_exceeded_lines()
            if exceeded:
                raise UserError(self._get_exceeded_tolerance_message(exceeded))
            self._apply_conditional_tolerance_split()
        return super()._action_done()
