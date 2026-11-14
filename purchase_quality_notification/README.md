# Purchase Quality Notification

Satınalma kalite kontrol ve transfer bildirim süreci.

## Özellikler

- **Satınalma KK (`quality_purchase_ok`)**: `product_extra_fields` modülündeki
  mevcut "Satınalma KK" (`quality_inspection_purchase`) işaretinin teknik
  karşılığıdır; ürün formunda ayrı bir kutu gösterilmez, mevcut kutu kullanılır.
- İşaretlenen her ürün şablonu için tek bir otomatik `quality.point` oluşur
  (`auto_purchase_tmpl_id` ile işaretlenir; başlık "Bileşenler", kontrol bazı
  Miktar, sıklık Tümü, kısmi test %100, tip Geçti-Kaldı, ekip Main Quality
  Team, operasyonlar şirketin tüm gelen transfer tipleri).
- İşaret kaldırılınca nokta arşivlenir, tekrar işaretlenince etkinleşir;
  yeni ürün varyantları noktaya otomatik eklenir.
- `stock.location.is_failure_location` (yalnızca dahili konumlar): işaretli
  tüm konumlar otomatik noktaların Arıza Lokasyonları alanına senkronize
  edilir; işaret kaldırıldığında çıkarılır.
- Gelen transferde KK kapsamlı ürün varsa "Kaliteye Gönder" butonu görünür.
  Buton `mail_template_purchase_quality_notify` şablonuyla Quality / User
  grubu üyelerine e-posta gönderir ve transfer chatter'ına kaydeder.
  İlk gönderimden sonra buton "Kaliteye Tekrar Bildir" olur.

## Notlar

- E-posta alıcıları, `quality.alert.team` modelinde üye alanı bulunmadığından
  **Quality / User** yetki grubundaki kullanıcıların (e-posta adresi tanımlı,
  dahili) partner'larıdır; adresler tekilleştirilir.
- Fiili e-posta teslimi için giden posta sunucusu (`ir.mail_server`)
  yapılandırması gerekir; gönderim başarısız olursa kullanıcı uyarılır ve
  başarısız e-posta chatter'da işaretli kalır.
- E-posta şablonu Ayarlar > Teknik > E-posta Şablonları altından
  düzenlenebilir (noupdate verisi).
