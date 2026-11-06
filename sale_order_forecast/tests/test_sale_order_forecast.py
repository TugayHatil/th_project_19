# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestSaleOrderForecast(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Forecast Müşteri",
        })
        cls.product_stock = cls.env["product.product"].create({
            "name": "Stoklu Ürün",
            "type": "consu",
            "is_storable": True,
        })
        cls.product_stock2 = cls.env["product.product"].create({
            "name": "Stoklu Ürün 2",
            "type": "consu",
            "is_storable": True,
        })
        cls.product_service = cls.env["product.product"].create({
            "name": "Hizmet Ürünü",
            "type": "service",
        })
        cls.quant = cls.env["stock.quant"]
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1)
        cls.stock_location = warehouse.lot_stock_id

    def _create_order(self, nature="forecast", product=None, qty=5.0, price=100.0):
        product = product or self.product_stock
        return self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_nature": nature,
            "order_line": [Command.create({
                "product_id": product.id,
                "product_uom_qty": qty,
                "price_unit": price,
            })],
        })

    # 1) Varsayılan nitelik Normal olmalı
    def test_01_default_nature_is_normal(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product_stock.id,
                "product_uom_qty": 1.0,
            })],
        })
        self.assertEqual(order.order_nature, "normal")

    # 2/4/5/6) Forecast teklif onaylanınca: sales order olmalı ama
    # teslimat emri, stok hareketi ve rezervasyon oluşmamalı
    def test_02_forecast_confirm_creates_no_delivery(self):
        order = self._create_order("forecast")
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.name and order.name != "New")
        self.assertFalse(order.picking_ids)
        self.assertFalse(order.order_line.move_ids)

    def test_03_forecast_confirm_no_stock_reservation(self):
        self.quant._update_available_quantity(
            self.product_stock, self.stock_location, 20.0)
        free_before = self.product_stock.free_qty
        order = self._create_order("forecast", qty=7.0)
        order.action_confirm()
        self.assertFalse(order.order_line.move_ids)
        self.assertEqual(self.product_stock.free_qty, free_before)

    # 3) Normal teklif onayı standart akışı bozmamalı
    def test_04_normal_confirm_creates_delivery(self):
        order = self._create_order("normal")
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.picking_ids)
        self.assertTrue(order.order_line.move_ids)

    # 8/9/10) Dönüştürme: aynı kayıt, aynı numara/satırlar, teslimat oluşmalı
    def test_05_convert_creates_delivery_same_order(self):
        order = self._create_order("forecast")
        order.action_confirm()
        name = order.name
        order.action_convert_to_normal()
        self.assertEqual(order.order_nature, "normal")
        self.assertTrue(order.forecast_converted)
        self.assertEqual(order.name, name)
        self.assertTrue(order.picking_ids)
        self.assertEqual(order.picking_ids.sale_id, order)
        self.assertTrue(order.order_line.move_ids)

    def test_06_convert_preserves_order_data(self):
        order = self._create_order("forecast", qty=3.0, price=250.0)
        order.client_order_ref = "REF-42"
        order.action_confirm()
        line_snapshot = order.order_line.read(
            ["product_id", "product_uom_qty", "price_unit"])[0]
        amount_total = order.amount_total
        order.action_convert_to_normal()
        line_after = order.order_line.read(
            ["product_id", "product_uom_qty", "price_unit"])[0]
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(order.client_order_ref, "REF-42")
        self.assertEqual(order.amount_total, amount_total)
        self.assertEqual(line_after, line_snapshot)

    # 11) Chatter kaydı
    def test_07_convert_posts_chatter_message(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_convert_to_normal()
        last_message = order.message_ids[0]
        self.assertIn("Kesinleşmiş siparişe dönüştürüldü", last_message.body)

    # 12) Tekrar dönüştürme engellenmeli
    def test_08_second_convert_is_blocked(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_convert_to_normal()
        picking_count = len(order.picking_ids)
        with self.assertRaises(UserError):
            order.action_convert_to_normal()
        self.assertEqual(len(order.picking_ids), picking_count)

    # 13) İptal edilmiş forecast dönüştürülemez
    def test_09_cancelled_forecast_cannot_convert(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_cancel()
        with self.assertRaises(UserError):
            order.action_convert_to_normal()

    # 14) Onaylı Normal sipariş Forecast'e çevrilemez
    def test_10_normal_to_forecast_blocked_after_confirm(self):
        order = self._create_order("normal")
        order.action_confirm()
        with self.assertRaises(UserError):
            order.order_nature = "forecast"

    # Onaylı forecast de write ile normal yapılamaz (sadece buton ile)
    def test_11_forecast_write_nature_blocked_after_confirm(self):
        order = self._create_order("forecast")
        order.action_confirm()
        with self.assertRaises(UserError):
            order.write({"order_nature": "normal"})

    # Teklif aşamasında iki yönde değişim serbest
    def test_12_nature_switchable_on_quotation(self):
        order = self._create_order("normal")
        order.order_nature = "forecast"
        self.assertEqual(order.order_nature, "forecast")
        order.order_nature = "normal"
        self.assertEqual(order.order_nature, "normal")

    # 15) Forecast siparişinden fatura oluşturulamaz
    def test_13_forecast_invoice_blocked(self):
        order = self._create_order("forecast")
        order.action_confirm()
        self.assertEqual(order.order_line.qty_to_invoice, 0.0)
        self.assertEqual(order.invoice_status, "no")
        with self.assertRaises(UserError):
            order._create_invoices()

    # Dönüştürme sonrası fatura oluşturulabilmeli
    def test_14_converted_order_invoiceable(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_convert_to_normal()
        self.assertEqual(order.invoice_status, "to invoice")
        self.assertTrue(order.order_line.qty_to_invoice > 0)

    # 17) Çok satırlı forecast dönüştürme
    def test_15_multi_line_convert(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_nature": "forecast",
            "order_line": [
                Command.create({
                    "product_id": self.product_stock.id,
                    "product_uom_qty": 2.0,
                }),
                Command.create({
                    "product_id": self.product_stock2.id,
                    "product_uom_qty": 4.0,
                }),
                Command.create({
                    "product_id": self.product_service.id,
                    "product_uom_qty": 1.0,
                }),
            ],
        })
        order.action_confirm()
        self.assertFalse(order.order_line.move_ids)
        order.action_convert_to_normal()
        stock_lines = order.order_line.filtered(
            lambda l: l.product_id.is_storable)
        self.assertTrue(stock_lines.move_ids)
        self.assertEqual(
            len(stock_lines.move_ids.filtered(lambda m: m.state != "cancel")),
            2)
        self.assertTrue(order.picking_ids)

    # 3.7) Dönüştürülmüş sipariş iptal edilip teklife dönse bile
    # tekrar Forecast yapılamaz
    def test_16_converted_cannot_return_to_forecast(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_convert_to_normal()
        order.action_cancel()
        order.action_draft()
        with self.assertRaises(UserError):
            order.order_nature = "forecast"

    # İptal edilip tekrar teklife dönen forecast, niteliğini korur
    def test_17_forecast_survives_draft_cycle(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_cancel()
        order.action_draft()
        self.assertEqual(order.order_nature, "forecast")
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.picking_ids)

    # Kilitli forecast siparişi dönüştürülebilir, kilit korunur
    def test_18_locked_forecast_convert(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.locked = True
        order.action_convert_to_normal()
        self.assertEqual(order.order_nature, "normal")
        self.assertTrue(order.locked)
        self.assertTrue(order.picking_ids)

    # Onaydan sonra eklenen satır da dönüştürmede teslimata dahil olur
    def test_19_convert_covers_lines_added_after_confirm(self):
        order = self._create_order("forecast", qty=2.0)
        order.action_confirm()
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": self.product_stock2.id,
            "product_uom_qty": 3.0,
        })
        # Forecast olduğu için yeni satır da stok kuralı tetiklemez
        self.assertFalse(order.order_line.move_ids)
        order.action_convert_to_normal()
        self.assertTrue(order.order_line.move_ids)
        self.assertTrue(order.picking_ids)

    # Onaylı forecast'te miktar değişikliği stok kuralı tetiklemez
    def test_20_qty_change_on_forecast_no_stock_rule(self):
        order = self._create_order("forecast", qty=2.0)
        order.action_confirm()
        order.order_line.product_uom_qty = 9.0
        self.assertFalse(order.order_line.move_ids)
        self.assertFalse(order.picking_ids)

    # 19) Satış siparişi niteliği diğer alanlardan bağımsız çalışır
    def test_21_nature_independent_of_other_fields(self):
        order = self._create_order("forecast")
        self.assertEqual(order.order_nature, "forecast")
        self.assertTrue(hasattr(order, "state"))
        self.assertEqual(order.state, "draft")
