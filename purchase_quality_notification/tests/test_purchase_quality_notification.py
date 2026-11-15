# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase


class TestPurchaseQualityNotification(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.template'].create({
            'name': 'KK Test Ürünü',
            'is_storable': True,
            'quality_purchase_ok': True,
        })
        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.supplier = cls.env['res.partner'].create({'name': 'KK Tedarikçi'})

    def _incoming_picking(self, tmpl=None):
        tmpl = tmpl or self.product
        return self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_in').id,
            'partner_id': self.supplier.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock_location.id,
            'move_ids': [(0, 0, {
                'name': 'move',
                'product_id': tmpl.product_variant_id.id,
                'product_uom_qty': 5,
                'location_id': self.env.ref('stock.stock_location_suppliers').id,
                'location_dest_id': self.stock_location.id,
            })],
        })

    def test_failure_location_requires_internal(self):
        supplier_loc = self.env['stock.location'].create({
            'name': 'Dahili Olmayan',
            'usage': 'view',
            'location_id': self.stock_location.id,
        })
        with self.assertRaises(ValidationError):
            supplier_loc.is_failure_location = True

    def test_show_quality_notify_visibility(self):
        picking = self._incoming_picking()
        self.assertTrue(picking.show_quality_notify)
        self.assertFalse(picking.quality_notified)
        outgoing = self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_out').id,
            'partner_id': self.supplier.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })
        self.assertFalse(outgoing.show_quality_notify)

    def test_no_automatic_check_on_confirm(self):
        # Confirming a receipt must NOT create quality checks — they are
        # only created via the per-line "Kaliteye Gönder" flag + button.
        picking = self._incoming_picking()
        picking.action_confirm()
        self.assertFalse(self.env['quality.check'].search(
            [('picking_id', '=', picking.id)]))

    def test_checks_created_only_for_marked_moves(self):
        other = self.env['product.template'].create({
            'name': 'KK Test Ürünü 2',
            'is_storable': True,
            'quality_purchase_ok': True,
        })
        picking = self._incoming_picking()
        picking.write({'move_ids': [(0, 0, {
            'name': 'move2',
            'product_id': other.product_variant_id.id,
            'product_uom_qty': 3,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock_location.id,
        })]})
        picking.action_confirm()
        move1, move2 = picking.move_ids
        move2.quality_send_ok = True
        checks = picking.move_ids.filtered(
            'quality_send_ok')._create_quality_checks()
        self.assertTrue(checks)
        for check in checks:
            self.assertEqual(check.move_line_id.move_id, move2)
            self.assertEqual(check.quality_state, 'none')
        # move1 untouched — no check on its line
        self.assertFalse(self.env['quality.check'].search_count(
            [('move_line_id', 'in', move1.move_line_ids.ids)]))
        # re-running does not duplicate pending checks
        again = move2._create_quality_checks()
        self.assertFalse(again)
