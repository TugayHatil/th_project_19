# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_round


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_purchase_tolerance_exceeded_lines(self):
        """Doğrulama sonrasında satınalma toleransını aşacak PO satırlarını döner.

        İade hareketleri (tedarikçiye giden) ve satınalma ile ilişkisi olmayan
        iç hareketler `_should_count_for_quantity_received` sayesinde hariç
        tutulur. Önceki kısmi teslimatlar `qty_received` üzerinden hesaba katılır.
        """
        aggregated = {}
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue
            moves = picking.move_ids.filtered(
                lambda m: m.purchase_line_id
                and m.state not in ('done', 'cancel')
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

    def button_validate(self):
        if not self.env.context.get('skip_purchase_tolerance_check'):
            exceeded = self._get_purchase_tolerance_exceeded_lines()
            if exceeded:
                wizard = self.env['purchase.tolerance.request.wizard'] \
                    .create_from_exceeded(self, exceeded)
                return wizard._get_open_action()
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
        return super()._action_done()
