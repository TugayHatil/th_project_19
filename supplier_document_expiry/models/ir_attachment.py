# -*- coding: utf-8 -*-
from odoo import models
from odoo.exceptions import AccessError


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _can_return_content(self, field_name=None, access_token=None):
        """Tedarikçi Belgeleri / Okuma grubundaki kullanıcılar belge
        kayıtlarını görebilir ancak belgeye bağlı dosyaların içeriğini
        (indirme/görüntüleme) açamaz."""
        user = self.env.user
        if (user.has_group(
                'supplier_document_expiry.group_supplier_document_read')
                and not user.has_group(
                    'supplier_document_expiry.group_supplier_document_user')):
            linked = self.filtered(
                lambda a: a.res_model == 'supplier.document' and a.res_id)
            unlinked = self - linked
            if unlinked:
                # Kayıt henüz yazılmadan yüklenen ekler res_id'siz
                # kalabilir; m2m ilişkisi üzerinden de kontrol et.
                linked |= self.browse(self.env['supplier.document']
                    .sudo().search(
                        [('attachment_ids', 'in', unlinked.ids)])
                    .attachment_ids.ids) & unlinked
            if linked:
                raise AccessError(self.env._(
                    'Tedarikçi belgelerine ait dosyaları indirme '
                    'yetkiniz bulunmuyor.'))
        return super()._can_return_content(
            field_name=field_name, access_token=access_token)
