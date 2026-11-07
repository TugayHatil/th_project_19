# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestSaleTender(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tender_type = cls.env.ref('sale_tender.sale_order_type_tender')
        cls.partner = cls.env["res.partner"].create({
            "name": "İhale Müşteri",
        })
        cls.other_partner = cls.env["res.partner"].create({
            "name": "Başka Müşteri",
        })
        cls.tender = cls.env["sale.tender"].create({
            "tender_no": "İHL-2026-001",
            "name": "Test İhalesi",
            "partner_id": cls.partner.id,
            "tender_date": "2026-11-01",
            "bid_deadline": "2026-11-30",
        })

    def _create_order(self, **kwargs):
        vals = {"partner_id": self.partner.id}
        vals.update(kwargs)
        return self.env["sale.order"].create(vals)

    def test_display_name(self):
        self.assertEqual(
            self.tender.display_name, "İHL-2026-001 - Test İhalesi")

    def test_create_quotation_defaults(self):
        action = self.tender.action_create_quotation()
        self.assertEqual(action["res_model"], "sale.order")
        self.assertEqual(action["view_mode"], "form")
        ctx = action["context"]
        self.assertEqual(ctx["default_partner_id"], self.partner.id)
        self.assertEqual(ctx["default_so_type_id"], self.tender_type.id)
        self.assertEqual(ctx["default_tender_id"], self.tender.id)
        self.assertEqual(ctx["default_user_id"], self.tender.user_id.id)

    def test_quotation_link_and_count(self):
        order = self._create_order(
            so_type_id=self.tender_type.id, tender_id=self.tender.id)
        self.assertEqual(order.tender_id, self.tender)
        self.assertEqual(self.tender.sale_order_count, 1)
        action = self.tender.action_view_quotations()
        self.assertEqual(action["domain"], [("tender_id", "=", self.tender.id)])

    def test_tender_required_when_type_tender(self):
        with self.assertRaises(ValidationError):
            self._create_order(so_type_id=self.tender_type.id)

    def test_tender_partner_mismatch_rejected(self):
        other_tender = self.env["sale.tender"].create({
            "tender_no": "İHL-2026-002",
            "name": "Diğer Müşteri İhalesi",
            "partner_id": self.other_partner.id,
        })
        with self.assertRaises(ValidationError):
            self._create_order(
                so_type_id=self.tender_type.id, tender_id=other_tender.id)

    def test_non_tender_types_allow_no_tender(self):
        order = self._create_order()
        self.assertFalse(order.so_type_id)
        self.assertFalse(order.tender_id)
        other_type = self.env["sale.order.type"].create({"name": "Yurtiçi"})
        order2 = self._create_order(so_type_id=other_type.id)
        self.assertFalse(order2.tender_id)

    def test_revision_copy_preserves_tender(self):
        order = self._create_order(
            so_type_id=self.tender_type.id, tender_id=self.tender.id)
        revision = order.copy()
        self.assertEqual(revision.so_type_id, self.tender_type)
        self.assertEqual(revision.tender_id, self.tender)
        self.assertEqual(revision.partner_id, self.partner)

    def test_linked_tender_cannot_be_deleted(self):
        self._create_order(
            so_type_id=self.tender_type.id, tender_id=self.tender.id)
        with self.assertRaises(UserError):
            self.tender.unlink()
        self.assertTrue(self.tender.exists())

    def test_unlinked_tender_can_be_deleted(self):
        tender = self.env["sale.tender"].create({
            "tender_no": "İHL-2026-003",
            "name": "Teklifsiz İhale",
            "partner_id": self.partner.id,
        })
        tender.unlink()
        self.assertFalse(tender.exists())

    def test_tender_user_readonly_access(self):
        user = self.env["res.users"].create({
            "name": "İhale Kullanıcı",
            "login": "tender_user_test",
            "group_ids": [
                (6, 0, [self.env.ref("sale_tender.group_tender_user").id])],
        })
        tender_as_user = self.tender.with_user(user)
        self.assertEqual(tender_as_user.name, "Test İhalesi")
        with self.assertRaises(UserError):
            tender_as_user.write({"name": "Değiştirilemez"})
        with self.assertRaises(UserError):
            self.env["sale.tender"].with_user(user).create({
                "tender_no": "İHL-2026-004",
                "name": "Yetkisiz",
                "partner_id": self.partner.id,
            })

    def test_lost_requires_reason(self):
        with self.assertRaises(ValidationError):
            self.tender.write({"state": "lost"})

    def test_lost_wizard_flow(self):
        reason = self.env["sale.tender.lost.reason"].create({
            "name": "Fiyat"})
        wizard = self.env["sale.tender.lost.wizard"].create({
            "tender_id": self.tender.id,
            "lost_reason_id": reason.id,
        })
        wizard.action_confirm()
        self.assertEqual(self.tender.state, "lost")
        self.assertEqual(self.tender.lost_reason_id, reason)
        # kaybedildi'den çıkınca neden temizlenir
        self.tender.write({"state": "draft"})
        self.assertFalse(self.tender.lost_reason_id)

    def test_competitors_tags(self):
        competitor = self.env["res.partner"].create({
            "name": "Rakip A.Ş.", "is_company": True})
        self.tender.competitor_ids = [(4, competitor.id)]
        self.assertIn(competitor, self.tender.competitor_ids)

    def test_tender_manager_full_access(self):
        user = self.env["res.users"].create({
            "name": "İhale Yönetici",
            "login": "tender_manager_test",
            "group_ids": [
                (6, 0, [self.env.ref("sale_tender.group_tender_manager").id])],
        })
        tender = self.env["sale.tender"].with_user(user).create({
            "tender_no": "İHL-2026-005",
            "name": "Yönetici İhalesi",
            "partner_id": self.partner.id,
        })
        tender.with_user(user).write({"state": "bid_submitted"})
        self.assertEqual(tender.state, "bid_submitted")
        tender.with_user(user).unlink()
        self.assertFalse(tender.exists())
