# -*- coding: utf-8 -*-
from odoo import _, fields, models
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
        data = Request._read_group(
            [('picking_id', 'in', self.ids)],
            groupby=['picking_id'], aggregates=['__count'])
        counts = {picking.id: count for picking, count in data}
        Return = self.env['stock.picking'].sudo()
        data = Return._read_group(
            [('tolerance_origin_picking_id', 'in', self.ids)],
            groupby=['tolerance_origin_picking_id'], aggregates=['__count'])
        ret_counts = {picking.id: count for picking, count in data}
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
        param = self.env['ir.config_parameter'].sudo().get_param(
            'purchase_tolerance.excess_location_id')
        location = self.env['stock.location'].sudo().browse(
            int(param)) if param else self.env['stock.location']
        if not location or location.usage != 'internal':
            raise UserError(_(
                'Tolerans dışı miktarın yönlendirileceği konum tanımlanmamış. '
                'Lütfen Envanter → Yapılandırma → Ayarlar altından '
                '"Tolerans Dışı Miktar Konumu" seçiniz.'))
        return location

    def _get_conditional_tolerance_request(self, order_line):
        """Bu transfer(ler) için satırın koşullu onaylanmış talebini döner."""
        return self.env['purchase.tolerance.request'].sudo().search([
            ('order_line_id', '=', order_line.id),
            ('state', '=', 'conditional'),
            ('picking_id', 'in', self.ids),
        ], limit=1, order='id desc')

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
            moves = picking.move_ids.filtered(
                lambda m: m.purchase_line_id
                and m.state not in ('done', 'cancel')
                and not m.is_tolerance_excess_move
                and m._should_count_for_quantity_received())
            if any(m.picked for m in moves):
                moves = moves.filtered(lambda m: m.picked)
            for move in moves:
                line = move.purchase_line_id
                qty = move.product_uom._compute_quantity(
                    move.quantity, line.product_uom_id, rounding_method='HALF-UP')
                if line.product_uom_id.compare(qty, 0) <= 0:
                    continue
                data = aggregated.setdefault(line.id, {
                    'order_line': line,
                    'pickings': self.env['stock.picking'].browse(),
                    'incoming_qty': 0.0,
                })
                data['pickings'] |= picking
                data['incoming_qty'] += qty

        exceeded = []
        for data in aggregated.values():
            line = data['order_line']
            projected = line.qty_received + data['incoming_qty']
            max_qty = line.product_qty * (1 + line.purchase_tolerance / 100.0)
            if float_compare(projected, max_qty,
                             precision_rounding=line.product_uom_id.rounding) <= 0:
                continue
            if data['pickings']._get_conditional_tolerance_request(line):
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
        tolerans dışı konuma yönlendirecek şekilde miktarı böler."""
        split_needed = False
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue
            moves = picking.move_ids.filtered(
                lambda m: m.purchase_line_id
                and m.state not in ('done', 'cancel')
                and not m.is_tolerance_excess_move
                and m._should_count_for_quantity_received())
            for move in moves.sorted('id'):
                request = picking._get_conditional_tolerance_request(
                    move.purchase_line_id)
                if request:
                    split_needed = True
        if not split_needed:
            return

        excess_loc = self._get_tolerance_excess_location()
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue
            caps = {}
            moves = picking.move_ids.filtered(
                lambda m: m.purchase_line_id
                and m.state not in ('done', 'cancel')
                and not m.is_tolerance_excess_move
                and m._should_count_for_quantity_received())
            for move in moves.sorted('id'):
                line = move.purchase_line_id
                request = picking._get_conditional_tolerance_request(line)
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
                if float_compare(
                        qty, allowed,
                        precision_rounding=line.product_uom_id.rounding) <= 0:
                    continue
                allowed_move_qty = line.product_uom_id._compute_quantity(
                    allowed, move.product_uom, rounding_method='HALF-UP')
                excess_move_qty = move.quantity - allowed_move_qty
                if excess_move_qty <= 0:
                    continue
                if move.product_uom.compare(allowed_move_qty, 0) <= 0:
                    move._action_cancel()
                else:
                    move.write({'quantity': allowed_move_qty, 'picked': True})
                excess_move = self.env['stock.move'].create({
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
                excess_move.write(
                    {'quantity': excess_move_qty, 'picked': True})
                request.sudo().move_ids = [
                    (6, 0, (request.move_ids | excess_move).ids)]

    def button_validate(self):
        if not self.env.context.get('skip_purchase_tolerance_check'):
            exceeded = self._get_purchase_tolerance_exceeded_lines()
            if exceeded:
                wizard = self.env['purchase.tolerance.request.wizard'] \
                    .create_from_exceeded(self, exceeded)
                return wizard._get_open_action()
            self._apply_conditional_tolerance_split()
        return super().button_validate()

    def _action_done(self):
        if not self.env.context.get('skip_purchase_tolerance_check'):
            exceeded = self._get_purchase_tolerance_exceeded_lines()
            if exceeded:
                message = _(
                    'Satınalma toleransı aşıldığı için mal kabul doğrulanamadı:'
                )
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
                raise UserError(message)
            self._apply_conditional_tolerance_split()
        return super()._action_done()
