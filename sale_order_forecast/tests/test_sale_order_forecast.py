# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests.common import TransactionCase


class TestSaleOrderForecast(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Öngörü Müşteri",
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
        cls.Wizard = cls.env["sale.order.nature.wizard"]
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

    def _confirm_via_wizard(self, order, nature):
        """Onay butonunun açtığı pencerede seçim yapma akışını simüle eder."""
        with patch.object(
                type(order), "_is_backend_button_call", return_value=True):
            action = order.action_confirm()
        if isinstance(action, dict):
            wizard = self.Wizard.browse(action["res_id"])
            return getattr(
                wizard,
                "action_select_confirmed" if nature == "confirmed"
                else "action_select_forecast")()
        return action

    # 1/2) Yeni teklifte nitelik boş olmalı ve kaydedilebilmeli
    def test_01_no_default_nature(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_line": [Command.create({
                "product_id": self.product_stock.id,
                "product_uom_qty": 1.0,
            })],
        })
        self.assertFalse(order.order_nature)
        self.assertEqual(order.state, "draft")

    # 3/4/6) Onayla, niteliksiz siparişi onaylamak yerine seçim penceresi açar
    def test_02_confirm_without_nature_opens_wizard(self):
        order = self._create_order(nature=False)
        with patch.object(
                type(order), "_is_backend_button_call", return_value=True):
            action = order.action_confirm()
        self.assertIsInstance(action, dict)
        self.assertEqual(action["res_model"], "sale.order.nature.wizard")
        self.assertEqual(action["target"], "new")
        # Pencere açılırken sipariş onaylanmaz
        self.assertEqual(order.state, "draft")
        self.assertFalse(order.order_nature)

    # 7) Pencerede Kesin seçimi → standart sipariş + teslimat
    def test_03_wizard_confirmed_creates_delivery(self):
        order = self._create_order(nature=False)
        self._confirm_via_wizard(order, "confirmed")
        self.assertEqual(order.order_nature, "confirmed")
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.was_confirmed)
        self.assertTrue(order.picking_ids)
        self.assertTrue(order.order_line.move_ids)

    # 8/9) Pencerede Öngörü seçimi → sale ama teslimat/hareket/rezervasyon yok
    def test_04_wizard_forecast_no_delivery(self):
        order = self._create_order(nature=False)
        self._confirm_via_wizard(order, "forecast")
        self.assertEqual(order.order_nature, "forecast")
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.name and order.name != "New")
        self.assertFalse(order.picking_ids)
        self.assertFalse(order.order_line.move_ids)

    def test_05_forecast_confirm_no_stock_reservation(self):
        self.quant._update_available_quantity(
            self.product_stock, self.stock_location, 20.0)
        free_before = self.product_stock.free_qty
        order = self._create_order("forecast", qty=7.0)
        order.action_confirm()
        self.assertFalse(order.order_line.move_ids)
        self.assertEqual(self.product_stock.free_qty, free_before)

    # Nitelik önceden seçilmişse onay doğrudan gerçekleşir
    def test_06_confirm_with_preset_nature(self):
        order = self._create_order("confirmed")
        res = order.action_confirm()
        self.assertNotIsInstance(res, dict)
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.picking_ids)

    # Entegrasyonlar için context ile otomatik nitelik
    def test_07_confirm_with_context_nature(self):
        order = self._create_order(nature=False)
        order.with_context(order_nature="forecast").action_confirm()
        self.assertEqual(order.order_nature, "forecast")
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.picking_ids)

    # Portal/ödeme/webhook gibi arayüz dışı onaylarda otomatik Kesin
    def test_08_non_ui_confirm_auto_confirmed(self):
        order = self._create_order(nature=False)
        order.action_confirm()  # test ortamında request yok → arayüz dışı
        self.assertEqual(order.order_nature, "confirmed")
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.picking_ids)

    # Birden fazla niteliksiz teklif arayüzden toplu onaylanamaz
    def test_09_multi_confirm_without_nature_blocked(self):
        orders = self._create_order(nature=False) | self._create_order(nature=False)
        with patch.object(
                type(orders), "_is_backend_button_call", return_value=True):
            with self.assertRaises(UserError):
                orders.action_confirm()
        self.assertFalse(orders.mapped("picking_ids"))

    # 11/12/13) Dönüştürme: aynı kayıt/numara, teslimat oluşmalı
    def test_09_convert_creates_delivery_same_order(self):
        order = self._create_order("forecast")
        order.action_confirm()
        name = order.name
        order.action_convert_to_normal()
        self.assertEqual(order.order_nature, "confirmed")
        self.assertTrue(order.forecast_converted)
        self.assertEqual(order.name, name)
        self.assertTrue(order.picking_ids)
        self.assertEqual(order.picking_ids.sale_id, order)
        self.assertTrue(order.order_line.move_ids)

    def test_10_convert_preserves_order_data(self):
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

    # 14) Chatter kaydı
    def test_11_convert_posts_chatter_message(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_convert_to_normal()
        last_message = order.message_ids[0]
        self.assertIn("Kesin siparişe dönüştürüldü", last_message.body)

    # 16) Tekrar dönüştürme engellenmeli
    def test_12_second_convert_is_blocked(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_convert_to_normal()
        picking_count = len(order.picking_ids)
        with self.assertRaises(UserError):
            order.action_convert_to_normal()
        self.assertEqual(len(order.picking_ids), picking_count)

    # 17) İptal edilmiş öngörü dönüştürülemez
    def test_13_cancelled_forecast_cannot_convert(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_cancel()
        with self.assertRaises(UserError):
            order.action_convert_to_normal()

    # 18) Kesin sipariş Öngörü'ye çevrilemez
    def test_14_confirmed_to_forecast_blocked(self):
        order = self._create_order("confirmed")
        order.action_confirm()
        with self.assertRaises(UserError):
            order.order_nature = "forecast"

    # Onaylı öngörü de write ile kesin yapılamaz (sadece buton ile)
    def test_15_forecast_write_nature_blocked_after_confirm(self):
        order = self._create_order("forecast")
        order.action_confirm()
        with self.assertRaises(UserError):
            order.write({"order_nature": "confirmed"})

    # Teklif aşamasında iki yönde değişim serbest
    def test_16_nature_switchable_on_quotation(self):
        order = self._create_order(nature=False)
        order.order_nature = "confirmed"
        self.assertEqual(order.order_nature, "confirmed")
        order.order_nature = "forecast"
        self.assertEqual(order.order_nature, "forecast")

    # İptal → taslak döngüsünde nitelik sıfırlanır, yeniden seçim yapılabilir
    def test_17_nature_cleared_after_cancel_redraft(self):
        order = self._create_order("confirmed")
        order.action_confirm()
        order.action_cancel()
        order.action_draft()
        self.assertFalse(order.order_nature)
        self.assertFalse(order.was_confirmed)
        self.assertFalse(order.forecast_converted)
        self._confirm_via_wizard(order, "forecast")
        self.assertEqual(order.order_nature, "forecast")
        self.assertFalse(order.picking_ids)

    # 10) Öngörü siparişinden fatura oluşturulamaz
    def test_18_forecast_invoice_blocked(self):
        order = self._create_order("forecast")
        order.action_confirm()
        self.assertEqual(order.order_line.qty_to_invoice, 0.0)
        self.assertEqual(order.invoice_status, "no")
        with self.assertRaises(UserError):
            order._create_invoices()

    # Dönüştürme sonrası fatura oluşturulabilmeli
    def test_19_converted_order_invoiceable(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_convert_to_normal()
        self.assertEqual(order.invoice_status, "to invoice")
        self.assertTrue(order.order_line.qty_to_invoice > 0)

    # 19) Çok satırlı öngörü dönüştürme
    def test_20_multi_line_convert(self):
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

    # Dönüştürülmüş sipariş de iptal → taslak ile sıfırlanır ve
    # yeni döngüde tekrar Öngörü seçilip dönüştürülebilir
    def test_21_converted_order_can_restart_cycle(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_convert_to_normal()
        order.action_cancel()
        order.action_draft()
        self.assertFalse(order.order_nature)
        self.assertFalse(order.forecast_converted)
        self._confirm_via_wizard(order, "forecast")
        self.assertEqual(order.order_nature, "forecast")
        order.action_convert_to_normal()
        self.assertTrue(order.forecast_converted)

    # İptal edilip tekrar teklife dönen öngörü boş nitelikle başlar
    def test_22_forecast_cleared_after_draft_cycle(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_cancel()
        order.action_draft()
        self.assertFalse(order.order_nature)
        self._confirm_via_wizard(order, "forecast")
        self.assertEqual(order.state, "sale")
        self.assertFalse(order.picking_ids)

    # Kilitli öngörü siparişi dönüştürülebilir, kilit korunur
    def test_23_locked_forecast_convert(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.locked = True
        order.action_convert_to_normal()
        self.assertEqual(order.order_nature, "confirmed")
        self.assertTrue(order.locked)
        self.assertTrue(order.picking_ids)

    # Onaydan sonra eklenen satır da dönüştürmede teslimata dahil olur
    def test_24_convert_covers_lines_added_after_confirm(self):
        order = self._create_order("forecast", qty=2.0)
        order.action_confirm()
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": self.product_stock2.id,
            "product_uom_qty": 3.0,
        })
        self.assertFalse(order.order_line.move_ids)
        order.action_convert_to_normal()
        self.assertTrue(order.order_line.move_ids)
        self.assertTrue(order.picking_ids)

    # Onaylı öngörüde miktar değişikliği stok kuralı tetiklemez
    def test_25_qty_change_on_forecast_no_stock_rule(self):
        order = self._create_order("forecast", qty=2.0)
        order.action_confirm()
        order.order_line.product_uom_qty = 9.0
        self.assertFalse(order.order_line.move_ids)
        self.assertFalse(order.picking_ids)
