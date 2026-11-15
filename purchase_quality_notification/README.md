# Purchase Quality Notification

Satınalma kalite kontrol ve transfer bildirim süreci.

## Özellikler

- **Satınalma KK (`quality_purchase_ok`)**: bu modüle ait bağımsız Boolean
  alandır; ürün formunun standart **Satınalma** sekmesindeki "Kalite Kontrol"
  grubunda gösterilir. Ürünün kalite ekibine gönderilebilir olduğunu işaretler.
  `product_extra_fields` modülündeki benzer işaret
  (`quality_inspection_purchase`) ile ilişkisi yoktur — iki modül birlikte
  kuruluysa iki ayrı kutu görünür.
- Transfer onaylandığında kalite kontrolü **otomatik oluşmaz**. Gelen
  transferin Operasyonlar listesinde her KK ürünlü satırda "KK'ya Gönder"
  (`quality_send_ok`) onay kutusu görünür; depocu istediği satırları
  işaretler.
- "Kaliteye Gönder" butonu yalnızca **işaretli** satırlar için standart
  `quality.check` kaydı oluşturur (kontrol bazı Miktar/`move_line`, tip
  Geçti-Kaldı, ekip Main Quality Team, ilk `is_failure_location` konumu
  arıza lokasyonu olarak atanır). Satırın zaten bekleyen kontrolü varsa
  yinelenmez; satırsız move için ürün bazlı kontrol açılır. İşaretler
  gönderim sonrası temizlenir.
- Aynı buton `mail_template_purchase_quality_notify` şablonuyla Quality /
  User grubu üyelerine e-posta gönderir ve transfer chatter'ına kaydeder.
  İlk gönderimden sonra buton "Kaliteye Tekrar Bildir" olur.
- `stock.location.is_failure_location` (yalnızca dahili konumlar):
  oluşturulan kontrollerin Arıza Lokasyonu alanını belirler.
- Operasyonlar listesindeki "Kalite Kontrol" (`quality_check_state`) kolonu
  satırın toplu kontrol durumunu gösterir (yok / yapılacak / geçti /
  başarısız).

## Notlar

- `quality.point.auto_purchase_tmpl_id` alanı, eski otomatik senkron
  döneminde oluşturulmuş noktaları tanımlamak için korunur; yeni nokta
  artık oluşturulmaz.
- E-posta alıcıları, `quality.alert.team` modelinde üye alanı bulunmadığından
  **Quality / User** yetki grubundaki kullanıcıların (e-posta adresi tanımlı,
  dahili) partner'larıdır; adresler tekilleştirilir.
- Fiili e-posta teslimi için giden posta sunucusu (`ir.mail_server`)
  yapılandırması gerekir; gönderim başarısız olursa kullanıcı uyarılır ve
  başarısız e-posta chatter'da işaretli kalır.
- E-posta şablonu Ayarlar > Teknik > E-posta Şablonları altından
  düzenlenebilir (noupdate verisi).
