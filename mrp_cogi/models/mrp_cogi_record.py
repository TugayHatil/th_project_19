# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class MrpCogiRecord(models.Model):
    """Üretim sırasında planlanan ile gerçekleşen bileşen tüketimi arasındaki
    farkın izlendiği COGI kaydı. Stok hareketinin kendisi değil, eksik kalmış
    otomatik tüketimin takip kaydıdır."""

    _name = 'mrp.cogi.record'
    _description = 'COGI - Üretim Hareket Hatası Kaydı'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char('COGI No', required=True, copy=False, readonly=True,
                       default=lambda self: _('Yeni'), index='trigram')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True,
                                 default=lambda self: self.env.company)
    state = fields.Selection([
        ('open', 'Açık'),
        ('reprocessing', 'Yeniden İşleniyor'),
        ('done', 'Başarılı'),
        ('closed', 'Düzeltmeden Kapatıldı'),
    ], string='Durum', required=True, default='open', readonly=True, tracking=True)

    # Kaynak üretim ve malzeme bilgileri
    production_id = fields.Many2one('mrp.production', string='Üretim Emri',
                                    readonly=True, index=True, ondelete='set null')
    production_name = fields.Char('Üretim Emri Referansı', readonly=True)
    finished_product_id = fields.Many2one('product.product', string='Üretilecek Ürün',
                                          readonly=True, ondelete='set null')
    product_id = fields.Many2one('product.product', string='Bileşen',
                                 readonly=True, index=True, ondelete='set null')
    component_name = fields.Char('Bileşen Referansı', readonly=True)
    source_move_id = fields.Many2one('stock.move', string='Kaynak Stok Hareketi',
                                     readonly=True, ondelete='set null')
    location_id = fields.Many2one('stock.location', string='Stok Konumu', readonly=True)
    location_dest_id = fields.Many2one('stock.location', string='Hedef Konum', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Birim', readonly=True)

    # Miktarlar (ürün birimi üzerinden, orijinal olay anındaki değerler)
    planned_qty = fields.Float('Planlanan Miktar', readonly=True, digits='Product Unit')
    consumed_qty = fields.Float('Tüketilen Miktar', readonly=True, digits='Product Unit')
    initial_missing_qty = fields.Float('İlk Eksik Miktar', readonly=True, digits='Product Unit')
    corrected_qty = fields.Float('Düzeltilen Miktar', compute='_compute_correction_qty',
                                 store=True, digits='Product Unit')
    remaining_qty = fields.Float('Eksik Miktar', compute='_compute_correction_qty',
                                 store=True, digits='Product Unit')

    # İşlem ve hata bilgileri
    operator_id = fields.Many2one('res.users', string='İşlemi Yapan', readonly=True)
    responsible_id = fields.Many2one('res.users', string='COGI Sorumlusu')
    error_message = fields.Text('Hata Nedeni', readonly=True)
    original_error_message = fields.Text('İlk Hata Mesajı', readonly=True)
    last_result_note = fields.Text('İşlem Notu', readonly=True)

    # Yeniden işleme bilgileri
    attempt_count = fields.Integer('Deneme Sayısı', readonly=True, default=0)
    last_processed_by = fields.Many2one('res.users', string='Son Denemeyi Yapan', readonly=True)
    last_processed_at = fields.Datetime('Son İşlem Tarihi', readonly=True)
    correction_move_ids = fields.One2many('stock.move', 'cogi_record_id',
                                          string='Oluşturulan Stok Hareketleri', readonly=True)
    correction_move_count = fields.Integer(compute='_compute_correction_move_count')

    # Kapatma bilgileri
    close_reason = fields.Selection([
        ('planning', 'Planlama hatası'),
        ('duplicate', 'Mükerrer kayıt'),
        ('mo_cancel', 'Üretim iptali nedeniyle gereksiz hareket'),
        ('no_consumption', 'Gerçekleşmeyen tüketim'),
        ('master_data', 'Yanlış ana veri'),
        ('other', 'Diğer'),
    ], string='Kapatma Nedeni', readonly=True)
    close_note = fields.Text('Kapatma Açıklaması', readonly=True)
    closed_by = fields.Many2one('res.users', string='Kapatan Kullanıcı', readonly=True)
    closed_at = fields.Datetime('Kapatma Tarihi', readonly=True)

    @api.depends('correction_move_ids.state', 'correction_move_ids.quantity',
                 'correction_move_ids.product_uom', 'initial_missing_qty', 'product_uom_id')
    def _compute_correction_qty(self):
        for rec in self:
            done_moves = rec.correction_move_ids.filtered(lambda m: m.state == 'done')
            qty = sum(
                m.product_uom._compute_quantity(m.quantity, rec.product_uom_id)
                for m in done_moves
            )
            rec.corrected_qty = qty
            rec.remaining_qty = max(rec.initial_missing_qty - qty, 0.0)

    @api.depends('correction_move_ids')
    def _compute_correction_move_count(self):
        for rec in self:
            rec.correction_move_count = len(rec.correction_move_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Yeni')) == _('Yeni'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mrp.cogi.record') or _('Yeni')
        return super().create(vals_list)

    def unlink(self):
        if not self.env.su:
            raise UserError(_('COGI kayıtları silinemez; kayıtlar yalnızca kapatılabilir.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Aksiyonlar
    # ------------------------------------------------------------------

    def action_reprocess(self):
        """Eksik miktarı kullanılabilir stoktan karşılayacak yeni bir stok
        hareketi oluşturur. Kısmi işleme desteklenir; yalnızca mevcut stok
        kadar miktar işlenir. Başarısız denemede kayıt açık kalır ve hata
        mesajı güncellenir."""
        self.ensure_one()
        self._check_reprocessable()
        # Eşzamanlı iki işlemin aynı eksik miktarı çift işlemesini engelle.
        self.env.cr.execute(
            'SELECT id FROM mrp_cogi_record WHERE id = %s FOR UPDATE', (self.id,))
        self.invalidate_recordset()
        self._check_reprocessable()
        if float_is_zero(self.remaining_qty, precision_rounding=self.product_uom_id.rounding):
            self._mark_done()
            return True

        self.write({
            'state': 'reprocessing',
            'attempt_count': self.attempt_count + 1,
            'last_processed_by': self.env.user.id,
            'last_processed_at': fields.Datetime.now(),
        })
        try:
            with self.env.cr.savepoint():
                move = self._create_correction_move()
        except Exception as exc:
            error = str(exc)
            note = _('COGI yeniden işleme başarısız. %(product)s için stok çıkışı '
                     'gerçekleştirilemedi. Hata: %(error)s',
                     product=self._component_display_name(), error=error)
            self.write({
                'state': 'open',
                'error_message': error,
                'last_result_note': note,
            })
            self.message_post(body=note)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Yeniden işleme başarısız'),
                    'message': error,
                    'type': 'warning',
                    'sticky': True,
                },
            }

        done_qty = move.product_uom._compute_quantity(move.quantity, self.product_uom_id)
        note = _('COGI yeniden işleme başarılı. %(product)s için %(qty)s %(uom)s '
                 'stok çıkışı gerçekleştirildi. Oluşturulan stok hareketi: %(move)s.',
                 product=self._component_display_name(), qty=done_qty,
                 uom=self.product_uom_id.display_name,
                 move=move.reference or move.name)
        if float_is_zero(self.remaining_qty, precision_rounding=self.product_uom_id.rounding):
            self._mark_done()
        else:
            self.state = 'open'
            note += ' ' + _('Kalan eksik miktar: %(qty)s %(uom)s',
                            qty=self.remaining_qty, uom=self.product_uom_id.display_name)
        self.write({
            'error_message': False,
            'last_result_note': note,
        })
        self.message_post(body=note)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Başarılı'),
                'message': note,
                'type': 'success',
                'sticky': False,
            },
        }

    def _check_reprocessable(self):
        if self.state not in ('open', 'reprocessing'):
            raise UserError(_('Yalnızca açık COGI kayıtları yeniden işlenebilir.'))
        if not self.product_id or not self.location_id:
            raise UserError(_('Kayıt yeniden işlenemiyor: bileşen veya stok konumu bilgisi eksik.'))

    def _mark_done(self):
        self.state = 'done'
        note = _('COGI kaydı başarıyla tamamlandı. Toplam düzeltilen miktar: %(qty)s %(uom)s',
                 qty=self.corrected_qty, uom=self.product_uom_id.display_name)
        self.message_post(body=note)

    def _close_without_correction(self, reason, note):
        self.ensure_one()
        self._check_reprocessable()
        if not note:
            note = ''
        result = _('COGI kaydı düzeltme yapılmadan kapatıldı. Kapatma nedeni: %(reason)s. '
                   'Açıklama: %(note)s Kapatan: %(user)s.',
                   reason=dict(self._fields['close_reason'].selection).get(reason),
                   note=note or _('Yok'), user=self.env.user.display_name)
        self.write({
            'state': 'closed',
            'close_reason': reason,
            'close_note': note,
            'closed_by': self.env.user.id,
            'closed_at': fields.Datetime.now(),
            'last_processed_by': self.env.user.id,
            'last_processed_at': fields.Datetime.now(),
            'last_result_note': result,
        })
        self.message_post(body=result)

    # ------------------------------------------------------------------
    # Düzeltme hareketi
    # ------------------------------------------------------------------

    def _get_available_qty(self):
        self.ensure_one()
        return self.env['stock.quant']._get_available_quantity(
            self.product_id, self.location_id)

    def _create_correction_move(self):
        """Kalan eksik miktar için yeni bir stock.move oluşturur, rezerve eder
        ve doğrular. Kullanılabilir stok kalan miktardan azsa yalnızca mevcut
        stok kadarı işlenir."""
        self.ensure_one()
        available = self._get_available_qty()
        rounding = self.product_uom_id.rounding
        if float_is_zero(available, precision_rounding=rounding) or available < 0:
            raise UserError(_('%(product)s için %(location)s konumunda kullanılabilir '
                              'stok bulunmuyor.', product=self._component_display_name(),
                              location=self.location_id.display_name))
        qty_to_do = min(available, self.remaining_qty)
        if float_is_zero(qty_to_do, precision_rounding=rounding):
            raise UserError(_('%(product)s için %(location)s konumunda kullanılabilir '
                              'stok bulunmuyor.', product=self._component_display_name(),
                              location=self.location_id.display_name))
        move = self.env['stock.move'].create(self._prepare_correction_move_vals(qty_to_do))
        move._action_confirm()
        move._action_assign()
        move.quantity = qty_to_do
        move.picked = True
        move._action_done()
        if move.state != 'done':
            raise UserError(_('Stok hareketi tamamlanamadı (durum: %s).', move.state))
        # Üretim emrinin bitmiş ürün satırlarıyla izlenebilirlik bağını kur.
        if self.production_id:
            finished_lines = self.production_id.move_finished_ids.move_line_ids
            if finished_lines and move.move_line_ids:
                finished_lines.write({
                    'consume_line_ids': [(4, ml.id) for ml in move.move_line_ids]
                })
        return move

    def _prepare_correction_move_vals(self, qty):
        self.ensure_one()
        return {
            'name': '%s - %s' % (self.name, self._component_display_name()),
            'company_id': self.company_id.id,
            'product_id': self.product_id.id,
            'product_uom': self.product_uom_id.id,
            'product_uom_qty': qty,
            'location_id': self.location_id.id,
            'location_dest_id': self.location_dest_id.id,
            'raw_material_production_id': self.production_id.id,
            'origin': self.production_name or self.name,
            'procure_method': 'make_to_stock',
            'additional': True,
            'cogi_record_id': self.id,
            'cogi_source_move_id': self.source_move_id.id,
        }

    def _component_display_name(self):
        return self.product_id.display_name or self.component_name or '?'

    # ------------------------------------------------------------------
    # Navigasyon
    # ------------------------------------------------------------------

    def action_view_correction_moves(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('stock.stock_move_action')
        action['domain'] = [('id', 'in', self.correction_move_ids.ids)]
        action['context'] = {'create': 0}
        if len(self.correction_move_ids) == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = self.correction_move_ids.id
        return action
