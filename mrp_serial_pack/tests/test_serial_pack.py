# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestSerialPack(TransactionCase):
    """BRD kabul testleri: seri numaralı üretimde Veri Al ile otomatik
    koli (5'li) ve palet (10 koli) oluşturma."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_serial = cls.env["product.product"].create({
            "name": "Packed Serial Product",
            "is_storable": True,
            "tracking": "serial",
        })
        cls.product_plain = cls.env["product.product"].create({
            "name": "Plain Product",
            "is_storable": True,
            "tracking": "none",
        })
        cls.box_type = cls.env.ref("mrp_serial_pack.package_type_box")
        cls.pallet_type = cls.env.ref("mrp_serial_pack.package_type_pallet")

    # ---------------------------------------------------------------
    # Yardımcılar
    # ---------------------------------------------------------------

    def _create_mo(self, qty, product=None, confirm=True):
        mo = self.env["mrp.production"].create({
            "product_id": (product or self.product_serial).id,
            "product_qty": qty,
            "product_uom_id": (product or self.product_serial).uom_id.id,
        })
        if confirm:
            mo.action_confirm()
        return mo

    def _boxes(self, mo):
        return mo.pack_package_ids.filtered(
            lambda p: p.package_type_id == self.box_type)

    def _pallets(self, mo):
        return mo.pack_package_ids.filtered(
            lambda p: p.package_type_id == self.pallet_type)

    def _box_fill(self, box, mo):
        return box._get_pack_fill(mo.product_id)

    def _pallet_children(self, pallet):
        return pallet.child_package_ids | pallet.child_package_dest_ids

    def _finished_move(self, mo):
        return mo.move_finished_ids.filtered(
            lambda m: m.product_id == mo.product_id and m.state != "cancel")

    # ---------------------------------------------------------------
    # Senaryo A: miktar alanı boş -> planlanan miktar hazırlanır
    # ---------------------------------------------------------------

    def test_full_fetch_planned_qty(self):
        mo = self._create_mo(100)
        mo.action_fetch_data()

        self.assertEqual(mo.state, "confirmed",
                         "Veri Al üretim emrini tamamlamamalıdır")
        self.assertEqual(len(mo.lot_producing_ids), 100)
        self.assertEqual(len(mo.move_finished_ids.move_line_ids), 100)

        boxes = self._boxes(mo)
        pallets = self._pallets(mo)
        self.assertEqual(len(boxes), 20)
        self.assertEqual(len(pallets), 2)

        for box in boxes:
            self.assertEqual(self._box_fill(box, mo), 5)
            self.assertRegex(box.name, r"^BOX\d{10}$")
        self.assertEqual(
            {p.name for p in pallets},
            {"PAL%010d" % i for i in range(1, 3)})

        ordered_boxes = boxes.sorted("id")
        ordered_pallets = pallets.sorted("id")
        self.assertEqual(
            set(ordered_boxes[:10].package_dest_id), set(ordered_pallets[:1]))
        self.assertEqual(
            set(ordered_boxes[10:].package_dest_id), set(ordered_pallets[1:]))

    # ---------------------------------------------------------------
    # Senaryo B: kısmi miktar (12 -> 3 koli, 1 palet; son koli 2 adet)
    # ---------------------------------------------------------------

    def test_partial_fetch_12(self):
        mo = self._create_mo(100)
        mo.pack_transfer_qty = 12
        mo.action_fetch_data()

        self.assertEqual(len(mo.lot_producing_ids), 12)
        boxes = self._boxes(mo).sorted("id")
        self.assertEqual(len(boxes), 3)
        self.assertEqual([self._box_fill(b, mo) for b in boxes], [5, 5, 2])
        pallets = self._pallets(mo)
        self.assertEqual(len(pallets), 1)
        self.assertEqual(len(self._pallet_children(pallets)), 3)
        self.assertEqual(mo.state, "confirmed")

    def test_partial_fetch_7(self):
        mo = self._create_mo(50)
        mo.pack_transfer_qty = 7
        mo.action_fetch_data()
        boxes = self._boxes(mo).sorted("id")
        self.assertEqual(len(boxes), 2)
        self.assertEqual([self._box_fill(b, mo) for b in boxes], [5, 2])

    # ---------------------------------------------------------------
    # Senaryo C: hedef sonradan büyütülür (12 -> 32)
    # ---------------------------------------------------------------

    def test_incremental_fetch(self):
        mo = self._create_mo(100)
        mo.pack_transfer_qty = 12
        mo.action_fetch_data()
        first_lots = mo.lot_producing_ids

        mo.pack_transfer_qty = 32
        mo.action_fetch_data()

        self.assertEqual(len(mo.lot_producing_ids), 32)
        self.assertEqual(len(mo.lot_producing_ids - first_lots), 20,
                         "Yalnızca 20 yeni seri oluşturulmalıdır")
        boxes = self._boxes(mo).sorted("id")
        self.assertEqual(len(boxes), 7)
        # 3. koli (eski kısmi koli) önce 5'e tamamlanmalıdır
        self.assertEqual(self._box_fill(boxes[2], mo), 5)
        self.assertEqual(self._box_fill(boxes[-1], mo), 2)
        self.assertEqual(len(self._pallets(mo)), 1)

    # ---------------------------------------------------------------
    # Aynı hedefle tekrar çalıştırma: yeni kayıt oluşmaz
    # ---------------------------------------------------------------

    def test_repeat_fetch_is_idempotent(self):
        mo = self._create_mo(100)
        mo.pack_transfer_qty = 37
        mo.action_fetch_data()
        lots_before = mo.lot_producing_ids
        boxes_before = self._boxes(mo)
        pallets_before = self._pallets(mo)

        mo.action_fetch_data()

        self.assertEqual(mo.lot_producing_ids, lots_before)
        self.assertEqual(self._boxes(mo), boxes_before)
        self.assertEqual(self._pallets(mo), pallets_before)

    # ---------------------------------------------------------------
    # Senaryo E: hedef düşürülürse kayıtlar korunur, uyarı verilir
    # ---------------------------------------------------------------

    def test_decrease_target_keeps_records(self):
        mo = self._create_mo(100)
        mo.pack_transfer_qty = 60
        mo.action_fetch_data()

        mo.pack_transfer_qty = 40
        result = mo.action_fetch_data()

        self.assertEqual(result["params"]["type"], "warning")
        self.assertEqual(len(mo.lot_producing_ids), 60)
        self.assertEqual(len(self._boxes(mo)), 12)
        self.assertEqual(len(self._pallets(mo)), 2)

    # ---------------------------------------------------------------
    # Doğrulamalar
    # ---------------------------------------------------------------

    def test_fetch_requires_confirmed_state(self):
        mo = self._create_mo(10, confirm=False)
        self.assertEqual(mo.state, "draft")
        with self.assertRaises(UserError):
            mo.action_fetch_data()

    def test_fetch_requires_serial_tracking(self):
        mo = self._create_mo(10, product=self.product_plain)
        with self.assertRaises(UserError):
            mo.action_fetch_data()

    def test_fetch_target_cannot_exceed_planned(self):
        mo = self._create_mo(50)
        mo.pack_transfer_qty = 60
        with self.assertRaises(UserError):
            mo.action_fetch_data()

    def test_fetch_on_cancelled_mo_fails(self):
        mo = self._create_mo(10)
        mo.action_cancel()
        with self.assertRaises(UserError):
            mo.action_fetch_data()

    # ---------------------------------------------------------------
    # Senaryo F: Veri Al + standart üretim tamamlama
    # ---------------------------------------------------------------

    def test_mark_done_after_fetch(self):
        mo = self._create_mo(6)
        mo.action_fetch_data()
        self.assertFalse(mo.state == "done")

        # Hazırlanan seriler satırlara yazılmaz; standart akışta seri-satır
        # eşleşmesi üretim tamamlanırken yapılır (`_check_sn_uniqueness`
        # satır üzerinde üretim serisi görürse hata verir).
        prepared_lines = self._finished_move(mo).move_line_ids
        self.assertEqual(len(prepared_lines), 6)
        self.assertFalse(prepared_lines.lot_id)
        self.assertTrue(all(prepared_lines.mapped("result_package_id")))

        mo.button_mark_done()

        self.assertEqual(mo.state, "done")
        box = self._boxes(mo)
        pallet = self._pallets(mo)
        self.assertEqual(len(box), 2)
        self.assertEqual(len(pallet), 1)
        # Üretim tamamlanınca koli->palet bağı gerçek hiyerarşiye dönüşür
        self.assertEqual(box.parent_package_id, pallet)
        # Seri numaralı ürünler kolinin içindeki quant'larda olmalıdır
        quants = self.env["stock.quant"].search([
            ("product_id", "=", self.product_serial.id),
            ("package_id", "in", box.ids),
        ])
        self.assertEqual(sum(quants.mapped("quantity")), 6)
        self.assertEqual(len(quants.lot_id), 6)

    def test_partial_mark_done_creates_backorder(self):
        mo = self._create_mo(10)
        mo.pack_transfer_qty = 6
        mo.action_fetch_data()

        result = mo.button_mark_done()
        if isinstance(result, dict) and result.get("res_model") == "mrp.production.backorder":
            wizard = Form(self.env["mrp.production.backorder"].with_context(
                **result["context"])).save()
            wizard.action_backorder()

        self.assertEqual(mo.state, "done")
        self.assertEqual(mo.qty_produced, 6)
        backorders = mo.production_group_id.production_ids - mo
        self.assertEqual(len(backorders), 1)
        self.assertEqual(backorders.product_qty, 4)
        # Backorder yeni bir üretimdir; hazırlanmış seriler ilk emirde kalır
        self.assertFalse(backorders.lot_producing_ids)
        box = self._boxes(mo)
        self.assertEqual(box.parent_package_id, self._pallets(mo))
        quants = self.env["stock.quant"].search([
            ("product_id", "=", self.product_serial.id),
            ("package_id", "in", box.ids),
        ])
        self.assertEqual(sum(quants.mapped("quantity")), 6)
