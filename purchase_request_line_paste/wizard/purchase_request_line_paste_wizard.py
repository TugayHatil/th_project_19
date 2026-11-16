# -*- coding: utf-8 -*-
import re
from datetime import datetime

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseRequestLinePasteWizard(models.TransientModel):
    _name = 'purchase.request.line.paste.wizard'
    _description = 'Satınalma Talebi Satır Yapıştırma Sihirbazı'

    request_id = fields.Many2one(
        'purchase.request', string='Satınalma Talebi',
        required=True, readonly=True)
    state = fields.Selection(
        [('input', 'Veri Girişi'), ('preview', 'Önizleme')],
        default='input', readonly=True)
    input_text = fields.Text(
        string='Ürün / Miktar / Tarih Listesi',
        help='Excel\'den kopyalanan liste: her satırda ürün kodu, miktar '
             've istek tarihi (sekme veya noktalı virgül ile ayrılmış; '
             'tarih boş bırakılabilir). İlk satır başlık olabilir, '
             'otomatik atlanır.')
    line_ids = fields.One2many(
        'purchase.request.line.paste.wizard.line', 'wizard_id',
        string='Önizleme Satırları', readonly=True)
    valid_line_count = fields.Integer(compute='_compute_line_counts')
    error_line_count = fields.Integer(compute='_compute_line_counts')

    @api.depends('line_ids.state')
    def _compute_line_counts(self):
        for wiz in self:
            states = wiz.line_ids.mapped('state')
            wiz.valid_line_count = states.count('ok')
            wiz.error_line_count = states.count('error')

    # ------------------------------------------------------------------
    # Ayrıştırma
    # ------------------------------------------------------------------

    def _split_row(self, row):
        """Bir satırı (kod, miktar, tarih) üçlüsüne ayırır; sütunlar
        konumsal — ilk hücre kod, ikinci miktar, üçüncü tarihtir."""
        for sep in ('\t', ';'):
            if sep in row:
                cells = [c.strip() for c in row.split(sep)]
                cells += [''] * (3 - len(cells))
                return cells[0], cells[1], cells[2]
        parts = row.split()
        parts += [''] * (3 - len(parts))
        return parts[0], parts[1], parts[2]

    def _strip_thousands(self, text, sep):
        """Binlik ayıracını yalnızca geçerli gruplamada kaldırır
        (örn. "1.234" → "1234"; "1.2.3" → None)."""
        if not sep or sep not in text:
            return text
        if re.match(r'^-?\d{1,3}(%s\d{3})+$' % re.escape(sep), text):
            return text.replace(sep, '')
        return None

    def _parse_qty(self, text):
        """Miktarı kullanıcının Odoo dil/biçim ayarına göre float'a çevirir."""
        raw = re.sub(r'\s', '', text or '')
        if not raw:
            return None
        lang = self.env['res.lang']._lang_get(self.env.user.lang)
        decimal_point = lang.decimal_point or '.'
        thousands_sep = lang.thousands_sep or ''
        candidates = []
        if decimal_point in raw:
            # "1.234,5" (tr_TR) / "1,234.5" (en_US): ondalık ayıracından böl,
            # tam kısımdaki binlikleri temizle
            if raw.count(decimal_point) != 1:
                return None
            int_part, frac = raw.split(decimal_point, 1)
            int_clean = self._strip_thousands(int_part, thousands_sep)
            if int_clean is None:
                return None
            candidates.append('%s.%s' % (int_clean, frac))
        elif thousands_sep:
            # Ondalık yok: "1.234" gibi gruplanmış binlikler → tamamı binlik
            grouped = self._strip_thousands(raw, thousands_sep)
            if grouped:
                candidates.append(grouped)
        candidates.append(raw)
        for candidate in candidates:
            try:
                return float(candidate)
            except ValueError:
                continue
        return None

    def _parse_date(self, text):
        """Tarihi kullanıcının Odoo dil/biçim ayarına göre date'e çevirir."""
        raw = re.sub(r'\s', '', text or '')
        if not raw:
            return None
        lang = self.env['res.lang']._lang_get(self.env.user.lang)
        lang_format = lang.date_format or '%d.%m.%Y'
        dmy = ['%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y',
               '%d.%m.%y', '%d/%m/%y', '%d-%m-%y']
        mdy = ['%m/%d/%Y', '%m.%d.%Y', '%m-%d-%Y',
               '%m/%d/%y', '%m.%d.%y', '%m-%d-%y']
        ymd = ['%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d']
        # Dil formatı öncelikli; sonra dilin ay/gün sırasına uygun fallback'ler
        month_first = lang_format.index('%m') < lang_format.index('%d')
        fmts = [lang_format] + (mdy + dmy if month_first else dmy + mdy) + ymd
        for fmt in dict.fromkeys(fmts):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    def _resolve_product(self, code, products_by_code):
        if not code:
            return False, _('Ürün kodu boş.')
        products = products_by_code.get(code)
        if not products:
            return False, _('Ürün kodu bulunamadı.')
        if len(products) > 1:
            return False, _('Bu kodla birden fazla ürün eşleşti.')
        if not products.purchase_ok:
            return False, _('Ürün satınalmaya açık değil.')
        return products, False

    def _products_by_code(self, codes):
        """Yapıştırılan tüm kodları tek sorguda product.product ile eşler."""
        Product = self.env['product.product']
        if not codes:
            return {}
        products = Product.search([
            ('default_code', 'in', list(codes)),
            '|', ('company_id', '=', False),
            ('company_id', '=', self.request_id.company_id.id),
        ])
        products_by_code = {}
        for product in products:
            products_by_code.setdefault(product.default_code, Product)
            products_by_code[product.default_code] |= product
        return products_by_code

    def _parse_input(self):
        """input_text'i wizard.line kayıtlarına dönüştürür."""
        parsed_rows = []
        codes = set()
        for idx, row in enumerate(
                (self.input_text or '').splitlines(), start=1):
            if not row.strip():
                continue
            code, qty_text, date_text = self._split_row(row)
            parsed_rows.append((idx, code, qty_text, date_text))
            if code:
                codes.add(code)
        products_by_code = self._products_by_code(codes)

        vals_list = []
        first = True
        for row_no, code, qty_text, date_text in parsed_rows:
            qty = self._parse_qty(qty_text)
            product, error = self._resolve_product(code, products_by_code)
            base = {'row_no': row_no, 'raw_code': code, 'raw_qty': qty_text,
                    'raw_date': date_text}
            if first and qty is None and error:
                # İlk satır iki yönden de veri değilse başlık sayılır
                vals_list.append(dict(
                    base, state='header',
                    message=_('Başlık satırı atlandı.')))
            elif error:
                vals_list.append(dict(base, state='error', message=error))
            elif qty is None:
                vals_list.append(dict(
                    base, state='error',
                    message=(_('Miktar sütunu boş.') if not qty_text
                             else _('Miktar geçerli bir sayı değil.'))))
            elif qty <= 0:
                vals_list.append(dict(
                    base, state='error',
                    message=_('Miktar sıfırdan büyük olmalıdır.')))
            elif date_text and not self._parse_date(date_text):
                vals_list.append(dict(
                    base, state='error',
                    message=_('Tarih geçerli değil.')))
            else:
                vals_list.append(dict(
                    base, state='ok', product_id=product.id,
                    product_qty=qty,
                    date_required=self._parse_date(date_text)))
            first = False
        return vals_list

    # ------------------------------------------------------------------
    # Aksiyonlar
    # ------------------------------------------------------------------

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_parse(self):
        self.ensure_one()
        if not (self.input_text or '').strip():
            raise UserError(_('Lütfen ürün ve miktar listesini yapıştırın.'))
        self.line_ids.unlink()
        vals_list = self._parse_input()
        self.env['purchase.request.line.paste.wizard.line'].create([
            dict(vals, wizard_id=self.id) for vals in vals_list])
        self.state = 'preview'
        return self._reopen()

    def action_back_to_input(self):
        self.ensure_one()
        self.state = 'input'
        return self._reopen()

    def action_apply(self):
        self.ensure_one()
        request = self.request_id
        if not request.is_editable:
            raise UserError(_(
                'Talebin durumu değişti; satır ekleme uygulanamadı.'))
        ok_lines = self.line_ids.filtered(lambda l: l.state == 'ok')
        if not ok_lines:
            raise UserError(_('Eklenecek geçerli satır bulunamadı.'))

        line_vals = []
        for line in ok_lines:
            product = line.product_id
            name = product.name
            if product.code:
                name = '[%s] %s' % (product.code, name)
            if product.description_purchase:
                name += '\n' + product.description_purchase
            line_vals.append({
                'request_id': request.id,
                'product_id': product.id,
                'name': name,
                'product_qty': line.product_qty,
                'product_uom_id': product.uom_id.id,
            })
            if line.date_required:
                line_vals[-1]['date_required'] = line.date_required
        self.env['purchase.request.line'].create(line_vals)

        skipped = len(self.line_ids) - len(ok_lines)
        body = Markup(
            _('Satır Yapıştırma ile %(added)s satır eklendi.',
              added=len(ok_lines)))
        if skipped:
            body += Markup(_(' %(skipped)s satır atlandı (hatalı/başlık).',
                             skipped=skipped))
        request.message_post(body=body)
        return {'type': 'ir.actions.act_window_close'}


class PurchaseRequestLinePasteWizardLine(models.TransientModel):
    _name = 'purchase.request.line.paste.wizard.line'
    _description = 'Satır Yapıştırma Önizleme Satırı'
    _order = 'row_no'

    wizard_id = fields.Many2one(
        'purchase.request.line.paste.wizard',
        required=True, ondelete='cascade')
    row_no = fields.Integer(string='Satır')
    raw_code = fields.Char(string='Ürün Kodu')
    raw_qty = fields.Char(string='Miktar (metin)')
    raw_date = fields.Char(string='Tarih (metin)')
    product_id = fields.Many2one('product.product', string='Ürün')
    product_qty = fields.Float(string='Miktar', digits='Product Unit')
    date_required = fields.Date(string='İstek Tarihi')
    state = fields.Selection(
        [('ok', 'Geçerli'), ('error', 'Hatalı'), ('header', 'Başlık')],
        default='ok')
    message = fields.Char(string='Durum')
