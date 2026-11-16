# -*- coding: utf-8 -*-

TR_OVERRIDES = (
    # (xmlid, field_name, translations)
    ('purchase_request.field_purchase_request__assigned_to',
     'field_description', {'tr_TR': 'Onaylayacak'}),
    ('purchase_request.field_purchase_request_line__assigned_to',
     'field_description', {'tr_TR': 'Onaylayacak'}),
    ('purchase_request.action_purchase_request_line_make_purchase_order',
     'name', {'tr_TR': 'Sipariş Oluştur'}),
    ('purchase_request.view_purchase_request_form',
     'arch_db', {'tr_TR': {'Create RFQ': 'Sipariş Oluştur'}}),
    ('purchase_request.view_purchase_request_line_make_purchase_order',
     'arch_db', {'tr_TR': {'Create RFQ': 'Sipariş Oluştur'}}),
)


def post_init_hook(env):
    for xmlid, field_name, translations in TR_OVERRIDES:
        record = env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.update_field_translations(field_name, translations)
