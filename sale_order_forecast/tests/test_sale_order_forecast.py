# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
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

    def _create_order(self, nature="forecast", product=None, qty=5.0,
                      price=100.0):
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

    def _transfer(self, order, selections):
        """Satır işaretleme + Kesin Siparişe Dönüştür akışını simüle eder.

        selections: {line: transfer_qty veya None(=kalan tamamı)} sözlüğü.
        Dönen act_window içindeki res_id'ten yeni siparişi çözer.
        """
        for line, qty in selections.items():
            line.to_transfer = True
            if qty is not None:
                line.transfer_qty = qty
        action = order.action_convert_to_confirmed()
        return self.env["sale.order"].browse(action["res_id"])

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
        orders = self._create_order(nature=False) | self._create_order(
            nature=False)
        with patch.object(
                type(orders), "_is_backend_button_call", return_value=True):
            with self.assertRaises(UserError):
                orders.action_confirm()
        self.assertFalse(orders.mapped("picking_ids"))

    # --- Parçalı aktarım (Kesin siparişe dönüştürme) ---

    def _three_line_order(self):
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "order_nature": "forecast",
            "order_line": [
                Command.create({
                    "product_id": self.product_stock.id,
                    "product_uom_qty": 100.0,
                }),
                Command.create({
                    "product_id": self.product_stock2.id,
                    "product_uom_qty": 100.0,
                }),
                Command.create({
                    "product_id": self.product_stock.id,
                    "product_uom_qty": 100.0,
                    "name": "Üçüncü satır",
                }),
            ],
        })
        order.action_confirm()
        return order

    # 11/12/13) Seçili satırlar yeni Kesin siparişe aktarılır
    def test_10_partial_transfer_creates_confirmed_order(self):
        order = self._three_line_order()
        line_a, line_b, line_c = order.order_line
        new_order = self._transfer(order, {line_a: 100.0, line_b: 60.0})
        # Kaynak sipariş yerinde kalır
        self.assertEqual(order.order_nature, "forecast")
        self.assertEqual(order.state, "sale")
        # Yeni sipariş Kesin ve onaylı
        self.assertEqual(new_order.order_nature, "confirmed")
        self.assertEqual(new_order.state, "sale")
        self.assertNotEqual(new_order.name, order.name)
        self.assertTrue(new_order.picking_ids)
        self.assertTrue(new_order.order_line.move_ids)
        # Yeni siparişte yalnızca seçili satırlar, aktarım miktarlarıyla
        self.assertEqual(len(new_order.order_line), 2)
        new_qtys = new_order.order_line.mapped("product_uom_qty")
        self.assertEqual(sorted(new_qtys), [60.0, 100.0])
        # Tamamı aktarılan A satırı kaynaktan silinir
        self.assertFalse(line_a.exists())
        # Kısmi aktarılan B satırının miktarı düşer
        self.assertEqual(line_b.product_uom_qty, 40.0)
        self.assertFalse(line_b.to_transfer)
        self.assertEqual(line_b.transfer_qty, 0.0)
        # Seçilmeyen C satırı korunur
        self.assertEqual(line_c.product_uom_qty, 100.0)

    # Bağlantılar: child→parent, parent→children, satır→satır
    def test_11_transfer_links(self):
        order = self._create_order("forecast", qty=10.0)
        order.action_confirm()
        line = order.order_line
        new_order = self._transfer(order, {line: 4.0})
        self.assertEqual(new_order.forecast_order_id, order)
        self.assertEqual(order.confirmed_order_ids, new_order)
        self.assertEqual(order.confirmed_order_count, 1)
        self.assertEqual(
            new_order.order_line.forecast_source_line_id, line)
        self.assertEqual(new_order.origin, order.name)

    # Aktarım miktarı boş bırakılırsa satırın tamamı aktarılır ve silinir
    def test_12_empty_transfer_qty_transfers_all(self):
        order = self._create_order("forecast", qty=7.0)
        order.action_confirm()
        line = order.order_line
        new_order = self._transfer(order, {line: None})
        self.assertEqual(new_order.order_line.product_uom_qty, 7.0)
        self.assertFalse(line.exists())
        self.assertFalse(order.order_line)

    # Parçalı aktarım tekrar edilebilir
    def test_13_multiple_partial_transfers(self):
        order = self._create_order("forecast", qty=10.0)
        order.action_confirm()
        line = order.order_line
        first = self._transfer(order, {line: 4.0})
        self.assertEqual(line.product_uom_qty, 6.0)
        self.assertTrue(order.has_transferable_lines)
        second = self._transfer(order, {line: 6.0})
        self.assertFalse(line.exists())
        self.assertFalse(order.has_transferable_lines)
        self.assertEqual(order.confirmed_order_count, 2)
        self.assertEqual(order.confirmed_order_ids, first | second)

    # Satır seçilmeden dönüştürme hatası
    def test_14_convert_without_selection_blocked(self):
        order = self._create_order("forecast")
        order.action_confirm()
        with self.assertRaises(UserError):
            order.action_convert_to_confirmed()
        self.assertFalse(order.confirmed_order_ids)

    # Aktarım miktarı sipariş miktarını aşamaz
    def test_15_transfer_qty_over_ordered_blocked(self):
        order = self._create_order("forecast", qty=5.0)
        order.action_confirm()
        order.order_line.to_transfer = True
        with self.assertRaises((UserError, ValidationError)):
            order.order_line.transfer_qty = 8.0
            order.action_convert_to_confirmed()
        self.assertFalse(order.confirmed_order_ids)

    # Tamamı aktarılan satır silindiğinden ikinci aktarım yapılamaz
    def test_16_no_lines_left_blocked(self):
        order = self._create_order("forecast", qty=5.0)
        order.action_confirm()
        self._transfer(order, {order.order_line: 5.0})
        with self.assertRaises(UserError):
            order.action_convert_to_confirmed()

    # 17) İptal edilmiş öngörüden aktarım yapılamaz
    def test_17_cancelled_forecast_cannot_convert(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.action_cancel()
        with self.assertRaises(UserError):
            order.order_line.to_transfer = True
            order.action_convert_to_confirmed()

    # Kilitli (done) öngörüden aktarım yapılamaz
    def test_18_done_forecast_cannot_convert(self):
        order = self._create_order("forecast")
        order.action_confirm()
        order.state = "done"
        order.order_line.to_transfer = True
        with self.assertRaises(UserError):
            order.action_convert_to_confirmed()

    # Kesin/niteliksiz siparişten aktarım yapılamaz
    def test_19_confirmed_order_cannot_convert(self):
        order = self._create_order("confirmed")
        order.action_confirm()
        with self.assertRaises(UserError):
            order.action_convert_to_confirmed()

    # 14) Chatter kaydı her iki tarafta
    def test_20_transfer_posts_chatter_messages(self):
        order = self._create_order("forecast", qty=5.0)
        order.action_confirm()
        new_order = self._transfer(order, {order.order_line: 3.0})
        self.assertIn("aktarıldı", order.message_ids[0].body)
        self.assertIn(new_order.name, order.message_ids[0].body)
        self.assertIn("Öngörü siparişinden aktarılarak",
                      new_order.message_ids[0].body)

    # Veri korunması: başlık ve satır bilgileri yeni siparişe taşınır
    def test_21_transfer_preserves_data(self):
        order = self._create_order("forecast", qty=10.0, price=250.0)
        order.client_order_ref = "REF-42"
        order.action_confirm()
        new_order = self._transfer(order, {order.order_line: 6.0})
        self.assertEqual(new_order.partner_id, self.partner)
        self.assertEqual(new_order.client_order_ref, "REF-42")
        self.assertEqual(new_order.order_line.price_unit, 250.0)
        self.assertEqual(new_order.order_line.product_id, self.product_stock)
        self.assertEqual(new_order.order_line.product_uom_qty, 6.0)

    # 10) Öngörü kaynaktan fatura yok; yeni Kesin siparişten var
    def test_22_invoice_rules(self):
        order = self._create_order("forecast", qty=10.0)
        order.action_confirm()
        self.assertEqual(order.order_line.qty_to_invoice, 0.0)
        with self.assertRaises(UserError):
            order._create_invoices()
        new_order = self._transfer(order, {order.order_line: 10.0})
        self.assertEqual(new_order.invoice_status, "to invoice")
        self.assertTrue(new_order.order_line.qty_to_invoice > 0)

    # 19) Çok satırlı aktarımda stok hareketleri yalnız stoklu ürünler için
    def test_23_multi_line_transfer_stock_moves(self):
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
        new_order = self._transfer(
            order, {l: None for l in order.order_line})
        stock_lines = new_order.order_line.filtered(
            lambda l: l.product_id.is_storable)
        self.assertEqual(
            len(stock_lines.move_ids.filtered(lambda m: m.state != "cancel")),
            2)
        service_line = new_order.order_line.filtered(
            lambda l: l.product_id == self.product_service)
        self.assertFalse(service_line.move_ids)
        self.assertTrue(new_order.picking_ids)
        self.assertFalse(order.picking_ids)  # kaynakta hâlâ teslimat yok

    # 18) Kesin sipariş Öngörü'ye çevrilemez
    def test_24_confirmed_to_forecast_blocked(self):
        order = self._create_order("confirmed")
        order.action_confirm()
        with self.assertRaises(UserError):
            order.order_nature = "forecast"

    # Onaylı öngörü write ile kesin yapılamaz
    def test_25_forecast_write_nature_blocked_after_confirm(self):
        order = self._create_order("forecast")
        order.action_confirm()
        with self.assertRaises(UserError):
            order.write({"order_nature": "confirmed"})

    # Aktarılan yeni siparişin niteliği de write ile değiştirilemez
    def test_26_transferred_order_nature_locked(self):
        order = self._create_order("forecast", qty=5.0)
        order.action_confirm()
        new_order = self._transfer(order, {order.order_line: 2.0})
        with self.assertRaises(UserError):
            new_order.write({"order_nature": "forecast"})

    # Teklif aşamasında iki yönde değişim serbest
    def test_27_nature_switchable_on_quotation(self):
        order = self._create_order(nature=False)
        order.order_nature = "confirmed"
        self.assertEqual(order.order_nature, "confirmed")
        order.order_nature = "forecast"
        self.assertEqual(order.order_nature, "forecast")

    # İptal → taslak döngüsünde nitelik sıfırlanır, yeniden seçim yapılabilir
    def test_28_nature_cleared_after_cancel_redraft(self):
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

    # İptal → taslak sonrası satır işaretleri de sıfırlanır
    def test_29_transfer_flags_cleared_after_redraft(self):
        order = self._create_order("forecast", qty=5.0)
        order.action_confirm()
        order.order_line.write({"to_transfer": True, "transfer_qty": 2.0})
        order.action_cancel()
        order.action_draft()
        self.assertFalse(order.order_line.to_transfer)
        self.assertEqual(order.order_line.transfer_qty, 0.0)

    # Onaylı öngörüde miktar değişikliği stok kuralı tetiklemez
    def test_30_qty_change_on_forecast_no_stock_rule(self):
        order = self._create_order("forecast", qty=2.0)
        order.action_confirm()
        order.order_line.product_uom_qty = 9.0
        self.assertFalse(order.order_line.move_ids)
        self.assertFalse(order.picking_ids)
