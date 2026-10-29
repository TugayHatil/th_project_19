# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMrpCogi(TransactionCase):
    """BRD §12 kabul senaryoları: eksik bileşen tüketimi için COGI kaydı,
    yeniden işleme (tam/kısmi/başarısız) ve düzeltmeden kapatma."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')

        cls.component = cls.env['product.product'].create({
            'name': 'COGI Bileşen',
            'is_storable': True,
            'uom_id': cls.uom_unit.id,
        })
        cls.finished = cls.env['product.product'].create({
            'name': 'COGI Mamul',
            'is_storable': True,
            'uom_id': cls.uom_unit.id,
        })
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.component.id,
                'product_qty': 1.0,
            })],
        })
        cls.Cogi = cls.env['mrp.cogi.record']
        cls.component2 = cls.env['product.product'].create({
            'name': 'COGI Bileşen 2',
            'is_storable': True,
            'uom_id': cls.uom_unit.id,
        })
        cls.bom_two = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [
                (0, 0, {'product_id': cls.component.id, 'product_qty': 1.0}),
                (0, 0, {'product_id': cls.component2.id, 'product_qty': 1.0}),
            ],
        })

    def _set_stock(self, qty):
        self.env['stock.quant']._update_available_quantity(
            self.component, self.stock_location, qty)

    def _create_mo(self, qty=100.0):
        mo = self.env['mrp.production'].create({
            'product_id': self.finished.id,
            'product_qty': qty,
            'bom_id': self.bom.id,
        })
        mo.action_confirm()
        return mo

    def _produce_with_consumption(self, mo, consumed_qty):
        """Bileşenden consumed_qty tüketilip üretim tamamlanır; tüketim
        uyarısı varsa mevcut miktar korunarak onaylanır."""
        raw_move = mo.move_raw_ids.filtered(lambda m: m.product_id == self.component)
        raw_move._set_quantity_done(consumed_qty)
        raw_move.picked = True
        mo.qty_producing = mo.product_qty
        action = mo.button_mark_done()
        if isinstance(action, dict):
            model = action.get('res_model')
            if model == 'mrp.consumption.warning':
                wizard = self.env[model].browse(action['res_id'])
                wizard.action_confirm()
                mo.invalidate_recordset()
        self.assertEqual(mo.state, 'done')
        return mo

    # ------------------------------------------------------------------

    def test_cogi_record_created_on_short_consumption(self):
        """100 planlanan / 95 tüketilen → 5 eksik için COGI kaydı."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)

        cogi = self.Cogi.search([('production_id', '=', mo.id)])
        self.assertEqual(len(cogi), 1)
        self.assertEqual(cogi.product_id, self.component)
        self.assertEqual(cogi.finished_product_id, self.finished)
        self.assertEqual(cogi.planned_qty, 100.0)
        self.assertEqual(cogi.consumed_qty, 95.0)
        self.assertEqual(cogi.initial_missing_qty, 5.0)
        self.assertEqual(cogi.remaining_qty, 5.0)
        self.assertEqual(cogi.state, 'open')
        self.assertTrue(cogi.name.startswith('COGI'))
        self.assertEqual(cogi.source_move_id.product_id, self.component)
        self.assertEqual(mo.cogi_count, 1)
        # Stok yalnızca gerçekten tüketilen 95 kadar düşmüş olmalı.
        self.assertEqual(
            self.env['stock.quant']._get_available_quantity(
                self.component, self.stock_location), 0.0)

    def test_no_cogi_when_fully_consumed(self):
        """Tam tüketimde COGI kaydı oluşmaz."""
        self._set_stock(100.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 100.0)
        self.assertFalse(self.Cogi.search([('production_id', '=', mo.id)]))

    def test_no_cogi_when_over_consumed(self):
        """Fazla tüketimde COGI kaydı oluşmaz."""
        self._set_stock(150.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 110.0)
        self.assertFalse(self.Cogi.search([('production_id', '=', mo.id)]))

    def test_reprocess_full(self):
        """Stok yeterliyse eksik miktar tek harekette işlenir."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])

        self._set_stock(5.0)
        cogi.action_reprocess()

        self.assertEqual(cogi.state, 'done')
        self.assertEqual(cogi.remaining_qty, 0.0)
        self.assertEqual(cogi.corrected_qty, 5.0)
        self.assertEqual(cogi.attempt_count, 1)
        self.assertEqual(len(cogi.correction_move_ids), 1)
        move = cogi.correction_move_ids
        self.assertEqual(move.state, 'done')
        self.assertEqual(move.quantity, 5.0)
        self.assertEqual(move.cogi_record_id, cogi)
        self.assertEqual(move.cogi_source_move_id, cogi.source_move_id)
        self.assertEqual(move.raw_material_production_id, mo)
        # Üretim emri ve hareket bağlantıları korunur.
        self.assertEqual(cogi.production_id, mo)
        self.assertEqual(
            self.env['stock.quant']._get_available_quantity(
                self.component, self.stock_location), 0.0)

    def test_reprocess_partial(self):
        """Stok eksik miktarın altındaysa kısmi işleme yapılır, kayıt açık kalır."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])

        self._set_stock(3.0)
        cogi.action_reprocess()

        self.assertEqual(cogi.state, 'open')
        self.assertEqual(cogi.remaining_qty, 2.0)
        self.assertEqual(cogi.corrected_qty, 3.0)
        self.assertEqual(cogi.initial_missing_qty, 5.0)

        # Kalan miktar için tekrar deneme.
        self._set_stock(2.0)
        cogi.action_reprocess()
        self.assertEqual(cogi.state, 'done')
        self.assertEqual(cogi.remaining_qty, 0.0)
        self.assertEqual(cogi.corrected_qty, 5.0)
        self.assertEqual(len(cogi.correction_move_ids), 2)
        # Toplam düzeltilen miktar ilk eksik miktarı aşmaz.
        self.assertLessEqual(cogi.corrected_qty, cogi.initial_missing_qty)

    def test_reprocess_no_stock_fails_safely(self):
        """Stok yoksa hareket oluşmaz, kayıt açık kalır, hata kaydedilir."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])

        result = cogi.action_reprocess()
        self.assertEqual(cogi.state, 'open')
        self.assertEqual(cogi.attempt_count, 1)
        self.assertTrue(cogi.error_message)
        self.assertFalse(cogi.correction_move_ids)
        self.assertEqual(result['params']['type'], 'warning')

    def test_reprocess_on_closed_or_done_fails(self):
        """Başarılı veya kapatılmış kayıt yeniden işlenemez."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])
        self._set_stock(5.0)
        cogi.action_reprocess()
        self.assertEqual(cogi.state, 'done')
        with self.assertRaises(UserError):
            cogi.action_reprocess()

    def test_close_without_correction(self):
        """Düzeltmeden kapatma: kayıt silinmez, stok hareketi oluşmaz."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])

        wizard = self.env['mrp.cogi.close.wizard'].create({
            'cogi_record_id': cogi.id,
            'close_reason': 'planning',
            'close_note': 'Reçetede miktar hatalı planlanmıştır.',
        })
        wizard.action_close()

        self.assertEqual(cogi.state, 'closed')
        self.assertEqual(cogi.close_reason, 'planning')
        self.assertTrue(cogi.closed_by)
        self.assertTrue(cogi.closed_at)
        self.assertFalse(cogi.correction_move_ids)
        with self.assertRaises(UserError):
            cogi.action_reprocess()

    def test_close_other_requires_note(self):
        """'Diğer' nedeni için açıklama zorunludur."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])
        wizard = self.env['mrp.cogi.close.wizard'].create({
            'cogi_record_id': cogi.id,
            'close_reason': 'other',
        })
        with self.assertRaises(UserError):
            wizard.action_close()

    def test_cogi_cannot_be_deleted(self):
        """COGI kaydı normal akışta silinemez."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])
        with self.assertRaises(UserError):
            cogi.unlink()
        self.assertTrue(cogi.exists())

    def test_mo_smart_button_action(self):
        """Üretim emri akıllı butonu ilgili COGI kayıtlarını açar."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        action = mo.action_view_cogi_records()
        self.assertEqual(action['res_model'], 'mrp.cogi.record')

    def test_zero_consumption_creates_full_cogi(self):
        """Bileşen hiç tüketilmezse tüm planlanan miktar COGI'ye düşer."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 0.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])
        self.assertEqual(len(cogi), 1)
        self.assertEqual(cogi.consumed_qty, 0.0)
        self.assertEqual(cogi.initial_missing_qty, 100.0)

    def test_stockless_component_does_not_block(self):
        """Stoğu olmayan bileşen üretimi bloklamaz; tüm miktar COGI'ye düşer.

        Produce All senaryosu: set_qty_producing her bileşen için tam
        miktarlı hareket satırları oluşturur; stoğu olmayan bileşenin
        satırları _post_inventory'de fiziksel stoğa kırpılır."""
        self._set_stock(100.0)  # yalnızca bileşen 1 stokta
        mo = self.env['mrp.production'].create({
            'product_id': self.finished.id,
            'product_qty': 100.0,
            'bom_id': self.bom_two.id,
        })
        mo.action_confirm()
        mo.qty_producing = 100.0
        mo.set_qty_producing()
        action = mo.button_mark_done()
        if isinstance(action, dict) and action.get('res_model') == 'mrp.consumption.warning':
            self.env['mrp.consumption.warning'].browse(action['res_id']).action_confirm()
            mo.invalidate_recordset()
        self.assertEqual(mo.state, 'done')

        # Bileşen 1 tam tüketilmiş olmalı.
        move1 = mo.move_raw_ids.filtered(lambda m: m.product_id == self.component)
        self.assertEqual(move1.quantity, 100.0)
        self.assertEqual(
            self.env['stock.quant']._get_available_quantity(
                self.component, self.stock_location), 0.0)

        # Bileşen 2 için COGI kaydı: planlanan 100, tüketilen 0, eksik 100.
        cogi = self.Cogi.search([
            ('production_id', '=', mo.id),
            ('product_id', '=', self.component2.id),
        ])
        self.assertEqual(len(cogi), 1)
        self.assertEqual(cogi.planned_qty, 100.0)
        self.assertEqual(cogi.consumed_qty, 0.0)
        self.assertEqual(cogi.initial_missing_qty, 100.0)
        self.assertEqual(cogi.state, 'open')
        # Bileşen 1 için COGI oluşmamalı.
        self.assertFalse(self.Cogi.search([
            ('production_id', '=', mo.id),
            ('product_id', '=', self.component.id),
        ]))

    def test_partial_stock_component_capped(self):
        """Kısmi stok: mevcut kadar tüketilir, kalan COGI'ye düşer."""
        self._set_stock(100.0)
        self.env['stock.quant']._update_available_quantity(
            self.component2, self.stock_location, 30.0)
        mo = self.env['mrp.production'].create({
            'product_id': self.finished.id,
            'product_qty': 100.0,
            'bom_id': self.bom_two.id,
        })
        mo.action_confirm()
        mo.qty_producing = 100.0
        mo.set_qty_producing()
        action = mo.button_mark_done()
        if isinstance(action, dict) and action.get('res_model') == 'mrp.consumption.warning':
            self.env['mrp.consumption.warning'].browse(action['res_id']).action_confirm()
            mo.invalidate_recordset()
        self.assertEqual(mo.state, 'done')

        move2 = mo.move_raw_ids.filtered(lambda m: m.product_id == self.component2)
        self.assertEqual(move2.quantity, 30.0)
        cogi = self.Cogi.search([
            ('production_id', '=', mo.id),
            ('product_id', '=', self.component2.id),
        ])
        self.assertEqual(cogi.initial_missing_qty, 70.0)
        # Sonra stok tamamlanıp yeniden işlenebilir.
        self.env['stock.quant']._update_available_quantity(
            self.component2, self.stock_location, 70.0)
        cogi.action_reprocess()
        self.assertEqual(cogi.state, 'done')
        self.assertEqual(cogi.corrected_qty, 70.0)

    def test_original_values_not_changed_after_reprocess(self):
        """Orijinal planlanan/tüketilen/eksik değerler düzeltme sonrası korunur."""
        self._set_stock(95.0)
        mo = self._create_mo()
        self._produce_with_consumption(mo, 95.0)
        cogi = self.Cogi.search([('production_id', '=', mo.id)])
        self._set_stock(5.0)
        cogi.action_reprocess()
        self.assertEqual(cogi.planned_qty, 100.0)
        self.assertEqual(cogi.consumed_qty, 95.0)
        self.assertEqual(cogi.initial_missing_qty, 5.0)
