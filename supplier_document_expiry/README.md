# Supplier Document Expiry

Tedarikçi belgelerinin merkezi yönetimi, geçerlilik tarihi takibi ve
seviye bazlı otomatik durum uyarıları.

## Özellikler

- **Belge Türleri**: Satınalma > Yapılandırma > Belge Türleri altında
  yalnızca yöneticiler tarafından yönetilir. Her tür için dinamik
  `Sarı Uyarı Günü` ve `Turuncu Uyarı Günü` tanımlanır
  (sarı > turuncu zorunlu). Pasifleştirilen türler yeni belgelerde
  seçilemez; geçmiş kayıtlar korunur.
- **Tedarikçi kartında hızlı giriş**: İş ortağı formunda
  "Sales & Purchase" sekmesi altında `Tedarikçi Belgeleri` listesi;
  satır üzerinden (ayrı form açmadan) belge adı, türü, sorumlu,
  geçerlilik tarihi ve dosyalar girilebilir.
- **Çoklu dosya**: Her belgeye `ir.attachment` altyapısıyla birden
  fazla dosya eklenebilir (PDF, Word, Excel vb.).
- **Otomatik durum**: Geçerlilik tarihine kalan güne göre
  🟢 Geçerli / 🟡 Sarı / 🟠 Turuncu / 🔴 Süresi Dolmuş; manuel
  değiştirilemez. Satır renklendirmesi turuncu ve kırmızıyı vurgular.
- **Merkezi liste**: Satınalma > Siparişler > Tedarikçi Belgeleri;
  tedarikçi kolonu ile tüm belgeler, durum ve tarih bazlı hazır
  filtreler (7/30 gün, bu ay, arşiv) ve gruplamalar.
- **Uyarılar**: Günlük cron durumları yeniden hesaplar; seviye
  değiştiğinde (yeşil→sarı→turuncu→kırmızı) sorumlu kullanıcıya
  (yoksa yönetici grubuna) aktivite uyarısı üretir. Aynı seviyede
  tekrarlı bildirim oluşmaz; iyileşmede açık uyarılar kapanır.

## Yetkiler

| Grup | Belge görüntüleme | Belge ekle/düzenle/sil | Dosya indirme | Belge türü yönetimi |
|------|-------------------|------------------------|---------------|---------------------|
| Okuma | ✔ | ✖ | ✖ | ✖ |
| Kullanıcı | ✔ | ✔ | ✔ | ✖ |
| Yönetici | ✔ | ✔ | ✔ | ✔ |

Okuma grubu indirmeyi `_can_return_content` seviyesinde engeller.
Gruplar Satınalma uygulaması görünürlüğü için satınalma
kullanıcı/yönetici gruplarını ima eder.

## Dağıtım Notu

Modül Python modelleri içerdiği için Uygulamalar > İçe Aktarma
Modülü ile yüklenemez; klasör addons path'e konup normal şekilde
kurulmalıdır.

## Başlangıç Verileri

Örnek türler: Lisans (30/7), Sözleşme (20/5), Sertifika (60/15).
