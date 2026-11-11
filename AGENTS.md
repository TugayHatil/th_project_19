# Agent Rules — th_project_19

## Ortam

- Odoo 19, host: `demo19.odoobulut.com` (extra-addons bu repodan kurulur).
- RPC yardımcısı: `C:\Users\tugay\AppData\Local\Temp\odoo_rpc.py`
  (`call(model, method, *args, **kw)`, `search_read(model, domain, fields)`).
- Modül yükseltme:
  ```python
  m = search_read('ir.module.module', [('name','=','mrp_long_term_planning')], ['id'])
  call('ir.module.module', 'button_immediate_upgrade', [m[0]['id']])
  ```
- Backend değişikliği sonrası: pull → module upgrade → test.
- Statik (JS/XML/SCSS) değişikliği sonrası: pull → Ctrl+F5 yeterli.
- `auto_plan` + `get_need_grid` gibi çağrılar `mrp.ltp.need` üzerinden yapılır;
  `get_need_grid` `[]` argümanla çağrılır, kwarg'lar dict olarak geçilir.

## E2E Test Protokolü (zorunlu)

Her akış değişikliğinde aşağıdaki kurallarla test yap:

1. Her aksiyonu UI'ın kullandığı aynı RPC yüzeyiyle çağır
   (`get_need_grid`, `auto_plan`, `confirm_operations`,
   `clear_need_schedule`, `clear_operation_drafts`, `get_operation_rows`) —
   doğrudan ORM çağırma.
2. HER aksiyon sonrası 3 yeri de assert et: op satırları + schedule
   kayıtları + grid satır durumları — tutarlılık şart.
3. Sekansları test et: plan→onayla→temizle→tekrar planla→başka satırı
   temizle → beklenen durumların hepsini doğrula.
4. UI tarafını da kontrol et: ilgili JS handler'ın aksiyon sonrası
   `loadGrid` VE `loadOps` çağırdığını doğrula (stale görünüm bug'ı için).
5. Çiftleşme/yetim kontrolü: aynı `(ürün, key-prefix)` altında birden
   fazla op/schedule olamaz; her op canlı bir need'e eşleşmeli.
6. Kenar durumlar: boş liste argümanları, kaymış `line_key`'ler,
   confirmed+locked karışımları, `[id, name]` formunda gelen m2o değerleri.
7. Test öncesi: env'yi temizle + modülün güncel olduğunu doğrula.
8. Test sonrası: oluşturduğun kalıntıları sil.
9. Bulduğun her tutarsızlığı raporla — düzeltmeden geçme.

## Bilinen Kırılganlıklar

- `line_key` = `bom:<pid>:<slot>:<tarih>` / `mv:<pick_id>` — tarih kısmı
  kayabilir; eşleştirmeler hep key-prefix üzerinden yapılmalı
  (`key.rsplit(':', 1)[0]`).
- Recordset'lerde `__dict__` yok; many2one değerleri int / `[id, name]` /
  isim olarak dönebilir — her formu normalize et.
- `("locked", "=", False)` NULL değerleri kaçırır; `"!=" True` kullan.
- Silinen kaydın alanını okuma → `MissingError`; unlink öncesi listele.
- `fields.Datetime.context_timestamp` aware döner; `localize` öncesi
  `tzinfo` soy.
