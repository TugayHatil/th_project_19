# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase
from odoo.tools import mute_logger


class TestProductExtraFields(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.responsible_1 = 'Ahmet Yilmaz'
        cls.responsible_2 = 'Mehmet Kaya'
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
            'responsible': cls.responsible_1,
        })
        cls.supervisor = cls.env['production.supervisor'].create({
            'name': 'D22',
            'responsible': cls.responsible_1,
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
        self.assertEqual(product.mip_responsible, self.responsible_1)

    def test_mip_responsible_change_propagates(self):
        product_1 = self._new_product(name='P1', mip_no=self.mip.id)
        product_2 = self._new_product(name='P2', mip_no=self.mip.id)
        self.mip.responsible = self.responsible_2
        self.assertEqual(product_1.mip_responsible, self.responsible_2)
        self.assertEqual(product_2.mip_responsible, self.responsible_2)

    def test_mip_selection_change_updates_responsible(self):
        mip_2 = self.env['mip.definition'].create({
            'name': 'MIP-002',
            'responsible': self.responsible_2,
        })
        product = self._new_product(mip_no=self.mip.id)
        product.mip_no = mip_2
        self.assertEqual(product.mip_responsible, self.responsible_2)
        product.mip_no = False
        self.assertFalse(product.mip_responsible)

    def test_production_supervisor_related(self):
        product = self._new_product(production_supervisor_no=self.supervisor.id)
        self.assertEqual(product.production_supervisor, self.responsible_1)

    def test_production_supervisor_change_propagates(self):
        product_1 = self._new_product(
            name='P1', production_supervisor_no=self.supervisor.id)
        product_2 = self._new_product(
            name='P2', production_supervisor_no=self.supervisor.id)
        self.supervisor.responsible = self.responsible_2
        self.assertEqual(product_1.production_supervisor, self.responsible_2)
        self.assertEqual(product_2.production_supervisor, self.responsible_2)

    def test_related_fields_stored_and_readonly(self):
        fields = self.env['product.template']._fields
        self.assertTrue(fields['mip_responsible'].store)
        self.assertTrue(fields['mip_responsible'].readonly)
        self.assertTrue(fields['production_supervisor'].store)
        self.assertTrue(fields['production_supervisor'].readonly)

    def test_mip_code_unique(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['mip.definition'].create({'name': 'MIP-001'})

    def test_production_supervisor_code_unique(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['production.supervisor'].create({'name': 'D22'})

    def test_used_definition_cannot_be_deleted(self):
        product = self._new_product(
            mip_no=self.mip.id,
            material_group_id=self.material_group.id,
        )
        with mute_logger('odoo.sql_db'), self.assertRaises(
                (UserError, IntegrityError)):
            self.mip.unlink()
        with mute_logger('odoo.sql_db'), self.assertRaises(
                (UserError, IntegrityError)):
            self.material_group.unlink()
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

    def test_negative_purchase_rounding_rejected(self):
        with self.assertRaises(ValidationError):
            self._new_product(purchase_order_qty_rounding=-2.0)

    def test_definition_name_is_trimmed(self):
        mip = self.env['mip.definition'].create({'name': '  MIP-009  '})
        self.assertEqual(mip.name, 'MIP-009')
        mip.write({'name': '  MIP-010 '})
        self.assertEqual(mip.name, 'MIP-010')

    def test_definition_access_rights(self):
        user = self.env['res.users'].create({
            'name': 'Restricted User',
            'login': 'pef_restricted_user',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        mip_as_user = self.env['mip.definition'].with_user(user)
        self.assertTrue(mip_as_user.search([]))
        with self.assertRaises(AccessError):
            mip_as_user.create({'name': 'MIP-FORBIDDEN'})
        with self.assertRaises(AccessError):
            mip_as_user.browse(self.mip.id).write({'responsible': 'X'})
        with self.assertRaises(AccessError):
            mip_as_user.browse(self.mip.id).unlink()

    def _new_user(self, login, *group_xmlids):
        return self.env['res.users'].create({
            'name': login,
            'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                *[self.env.ref(xmlid).id for xmlid in group_xmlids],
            ])],
        })

    def test_sub_type_field_on_product(self):
        sub_type = self.env['product.sub.type'].create({
            'name': 'AST-01', 'description': 'Test alt türü'})
        product = self._new_product(sub_type_id=sub_type.id)
        self.assertEqual(product.sub_type_id, sub_type)

    def test_sub_type_code_unique(self):
        self.env['product.sub.type'].create({'name': 'AST-DUP'})
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['product.sub.type'].create({'name': 'AST-DUP'})

    def test_sub_type_has_chatter(self):
        self.assertIn('message_ids', self.env['product.sub.type']._fields)

    def test_sub_type_access_rights(self):
        user = self._new_user('pef_sub_type_reader')
        sub_as_user = self.env['product.sub.type'].with_user(user)
        self.assertTrue(sub_as_user.search([]))
        with self.assertRaises(AccessError):
            sub_as_user.create({'name': 'AST-FORBIDDEN'})
        manager = self._new_user(
            'pef_sub_type_manager',
            'product_extra_fields.group_product_sub_type_manager')
        sub_as_manager = self.env['product.sub.type'].with_user(manager)
        sub_type = sub_as_manager.create({'name': 'AST-MGR'})
        sub_type.write({'description': 'güncellendi'})
        self.assertTrue(sub_type.unlink())

    def test_material_group_manager_access_rights(self):
        user = self._new_user('pef_mg_reader')
        mg_as_user = self.env['product.material.group'].with_user(user)
        self.assertTrue(mg_as_user.search([]))
        with self.assertRaises(AccessError):
            mg_as_user.create({'name': 'MG-FORBIDDEN'})
        manager = self._new_user(
            'pef_mg_manager',
            'product_extra_fields.group_material_group_manager')
        mg_as_manager = self.env['product.material.group'].with_user(manager)
        group = mg_as_manager.create({'name': 'MG-MGR'})
        group.write({'name': 'MG-MGR-2'})
        self.assertTrue(group.unlink())

    def test_planning_fields(self):
        product = self._new_product(
            moq=10.0, spq=5.0, leadtime=3, safety_stock=2.0,
            purchase_load_group_id=self.location.id,
            sale_load_group_id=self.location.id,
            foreign_trade_group='import')
        self.assertEqual(product.moq, 10.0)
        self.assertEqual(product.spq, 5.0)
        self.assertEqual(product.leadtime, 3)
        self.assertEqual(product.safety_stock, 2.0)
        self.assertEqual(product.purchase_load_group_id, self.location)
        self.assertEqual(product.sale_load_group_id, self.location)
        self.assertEqual(product.foreign_trade_group, 'import')
        product.foreign_trade_group = 'export'
        self.assertEqual(product.foreign_trade_group, 'export')

    def test_negative_planning_values_rejected(self):
        with self.assertRaises(ValidationError):
            self._new_product(moq=-1.0)
        with self.assertRaises(ValidationError):
            self._new_product(leadtime=-5)

    def test_product_count_and_smartbutton_action(self):
        self._new_product(
            name='PA', material_group_id=self.material_group.id)
        self._new_product(
            name='PB', material_group_id=self.material_group.id)
        self._new_product(name='PC')
        self.assertEqual(self.material_group.product_count, 2)
        action = self.material_group.action_view_products()
        self.assertEqual(action['res_model'], 'product.template')
        self.assertIn(
            ('material_group_id', '=', self.material_group.id),
            action['domain'])
        sub_type = self.env['product.sub.type'].create({'name': 'AST-CNT'})
        self._new_product(name='PD', sub_type_id=sub_type.id)
        self.assertEqual(sub_type.product_count, 1)
        action = sub_type.action_view_products()
        self.assertIn(('sub_type_id', '=', sub_type.id), action['domain'])
