# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.exceptions import UserError
from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestProductExtraFields(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({'name': 'Ahmet Yilmaz'})
        cls.employee_2 = cls.env['hr.employee'].create({'name': 'Mehmet Kaya'})
        cls.location = cls.env['stock.location'].create({
            'name': 'Test Internal Location',
            'usage': 'internal',
        })
        cls.material_group = cls.env['product.material.group'].create({
            'name': 'MG-01',
        })
        cls.external_group = cls.env['product.external.material.group'].create({
            'name': 'EMG-01',
        })
        cls.mip = cls.env['mip.definition'].create({
            'name': 'MIP-001',
            'responsible_id': cls.employee.id,
        })
        cls.supervisor = cls.env['production.supervisor'].create({
            'name': 'D22',
            'responsible_id': cls.employee.id,
        })

    def _new_product(self, **values):
        values.setdefault('name', 'Test Product')
        return self.env['product.template'].create(values)

    def test_general_extra_fields(self):
        product = self._new_product(
            old_default_code='OLD-123',
            material_group_id=self.material_group.id,
            external_material_group_id=self.external_group.id,
            validity_start_date='2026-01-15',
            production_storage_location=self.location.id,
            external_procurement_storage_location=self.location.id,
        )
        self.assertEqual(product.old_default_code, 'OLD-123')
        self.assertEqual(product.material_group_id, self.material_group)
        self.assertEqual(product.external_material_group_id, self.external_group)
        self.assertEqual(str(product.validity_start_date), '2026-01-15')
        self.assertEqual(product.production_storage_location, self.location)
        self.assertEqual(
            product.external_procurement_storage_location, self.location)

    def test_mip_responsible_related(self):
        product = self._new_product(mip_no=self.mip.id)
        self.assertEqual(product.mip_responsible_id, self.employee)

    def test_mip_responsible_change_propagates(self):
        product_1 = self._new_product(name='P1', mip_no=self.mip.id)
        product_2 = self._new_product(name='P2', mip_no=self.mip.id)
        self.mip.responsible_id = self.employee_2
        self.assertEqual(product_1.mip_responsible_id, self.employee_2)
        self.assertEqual(product_2.mip_responsible_id, self.employee_2)

    def test_mip_selection_change_updates_responsible(self):
        mip_2 = self.env['mip.definition'].create({
            'name': 'MIP-002',
            'responsible_id': self.employee_2.id,
        })
        product = self._new_product(mip_no=self.mip.id)
        product.mip_no = mip_2
        self.assertEqual(product.mip_responsible_id, self.employee_2)
        product.mip_no = False
        self.assertFalse(product.mip_responsible_id)

    def test_production_supervisor_related(self):
        product = self._new_product(production_supervisor_no=self.supervisor.id)
        self.assertEqual(product.production_supervisor_id, self.employee)

    def test_production_supervisor_change_propagates(self):
        product_1 = self._new_product(
            name='P1', production_supervisor_no=self.supervisor.id)
        product_2 = self._new_product(
            name='P2', production_supervisor_no=self.supervisor.id)
        self.supervisor.responsible_id = self.employee_2
        self.assertEqual(product_1.production_supervisor_id, self.employee_2)
        self.assertEqual(product_2.production_supervisor_id, self.employee_2)

    def test_related_fields_stored_and_readonly(self):
        fields = self.env['product.template']._fields
        self.assertTrue(fields['mip_responsible_id'].store)
        self.assertTrue(fields['mip_responsible_id'].readonly)
        self.assertTrue(fields['production_supervisor_id'].store)
        self.assertTrue(fields['production_supervisor_id'].readonly)

    def test_mip_code_unique(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['mip.definition'].create({'name': 'MIP-001'})

    def test_production_supervisor_code_unique(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['production.supervisor'].create({'name': 'D22'})

    def test_used_definition_cannot_be_deleted(self):
        product = self._new_product(mip_no=self.mip.id)
        with mute_logger('odoo.sql_db'), self.assertRaises(
                (UserError, IntegrityError)):
            self.mip.unlink()
        self.assertTrue(product.exists())

    def test_unused_definition_can_be_deleted(self):
        mip = self.env['mip.definition'].create({'name': 'MIP-003'})
        self.assertTrue(mip.unlink())

    def test_quality_inspection_defaults_and_write(self):
        product = self._new_product()
        self.assertFalse(product.quality_inspection_production)
        self.assertFalse(product.quality_inspection_purchase)
        product.write({
            'quality_inspection_production': True,
            'quality_inspection_purchase': True,
        })
        self.assertTrue(product.quality_inspection_production)
        self.assertTrue(product.quality_inspection_purchase)

    def test_purchase_fields(self):
        product = self._new_product(
            purchase_order_qty_rounding=5.0,
            purchase_group='direct',
        )
        self.assertEqual(product.purchase_order_qty_rounding, 5.0)
        self.assertEqual(product.purchase_group, 'direct')
        product.purchase_group = 'indirect'
        self.assertEqual(product.purchase_group, 'indirect')
