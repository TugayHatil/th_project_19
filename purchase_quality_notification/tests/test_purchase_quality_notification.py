# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase


class TestPurchaseQualityNotification(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Point = cls.env['quality.point'].with_context(active_test=False)
        cls.product = cls.env['product.template'].create({
            'name': 'KK Test Ürünü',
        })
        cls.stock_location = cls.env.ref('stock.stock_location_stock')
        cls.supplier = cls.env['res.partner'].create({'name': 'KK Tedarikçi'})

    def _auto_point(self, template):
        return self.Point.search(
            [('auto_purchase_tmpl_id', '=', template.id)], limit=1)

    def test_point_created_when_flagged(self):
        self.product.quality_purchase_ok = True
        point = self._auto_point(self.product)
        self.assertTrue(point)
        self.assertTrue(point.active)
        self.assertEqual(point.title, 'Bileşenler')
        self.assertEqual(point.measure_on, 'move_line')
        self.assertEqual(point.measure_frequency_type, 'all')
        self.assertEqual(point.testing_percentage_within_lot, 100.0)
        self.assertEqual(point.test_type_id.technical_name, 'passfail')
        self.assertEqual(set(point.product_ids.ids),
                         set(self.product.product_variant_ids.ids))
        self.assertTrue(all(t.code == 'incoming' for t in point.picking_type_ids))

    def test_no_duplicate_point_on_rewrite(self):
        self.product.quality_purchase_ok = True
        self.product.write({'name': 'KK Test Ürünü v2'})
        self.assertEqual(
            self.Point.search_count(
                [('auto_purchase_tmpl_id', '=', self.product.id)]), 1)

    def test_point_archived_and_reactivated(self):
        self.product.quality_purchase_ok = True
        point = self._auto_point(self.product)
        self.product.quality_purchase_ok = False
        self.assertFalse(point.active)
        self.product.quality_purchase_ok = True
        self.assertTrue(point.active)
        self.assertEqual(
            self.Point.search_count(
                [('auto_purchase_tmpl_id', '=', self.product.id)]), 1)

    def test_manual_points_not_touched(self):
        manual = self.env['quality.point'].create({
            'title': 'Manuel Nokta',
            'product_ids': [(6, 0, self.product.product_variant_ids.ids)],
        })
        self.product.quality_purchase_ok = True
        self.product.quality_purchase_ok = False
        self.assertTrue(manual.active)
        manual.unlink()

    def test_failure_location_requires_internal(self):
        supplier_loc = self.env['stock.location'].create({
            'name': 'Dahili Olmayan',
            'usage': 'view',
            'location_id': self.stock_location.id,
        })
        with self.assertRaises(ValidationError):
            supplier_loc.is_failure_location = True

    def test_failure_location_sync(self):
        self.product.quality_purchase_ok = True
        point = self._auto_point(self.product)
        loc = self.env['stock.location'].create({
            'name': 'Arıza Konumu',
            'usage': 'internal',
            'location_id': self.stock_location.id,
            'is_failure_location': True,
        })
        self.assertIn(loc, point.failure_location_ids)
        loc.is_failure_location = False
        self.assertNotIn(loc, point.failure_location_ids)

    def test_show_quality_notify_visibility(self):
        self.product.quality_purchase_ok = True
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_in').id,
            'partner_id': self.supplier.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.stock_location.id,
            'move_ids': [(0, 0, {
                'name': 'move',
                'product_id': self.product.product_variant_id.id,
                'product_uom_qty': 5,
                'product_uom': self.product.uom_id.id,
                'location_id': self.env.ref('stock.stock_location_suppliers').id,
                'location_dest_id': self.stock_location.id,
            })],
        })
        self.assertTrue(picking.show_quality_notify)
        self.assertFalse(picking.quality_notified)
        outgoing = self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_out').id,
            'partner_id': self.supplier.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })
        self.assertFalse(outgoing.show_quality_notify)
