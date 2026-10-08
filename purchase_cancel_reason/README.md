# Purchase Cancel Reason

Satınalma siparişleri iptal edilirken standartlaştırılmış **İptal
Nedeni** alınması ve iptal bilgilerinin geriye dönük analiz
edilebilmesi.

## Özellikler

- **İptal Nedenleri**: Satınalma > Yapılandırma > İptal Nedenleri
  altında yönetilebilir tanım yapısı (Sıra, Ad, Diğer, Aktif).
  Pasifleştirilen nedenler yeni işlemlerde seçilemez; geçmiş
  kayıtlardaki neden bilgisi korunur.
- **Aşamaya göre popup**: `sent`, `to approve` ve `purchase`
  durumlarında İptal Et aksiyonu İptal Nedeni popup'ı açar.
  `draft` durumunda popup açılmaz, sipariş doğrudan iptal edilir.
  Liste görünümünden toplu iptalde de aynı popup kullanılır.
- **Zorunlu neden**: Neden seçilmeden iptal tamamlanamaz; "Vazgeç"
  seçilirse sipariş durumu değişmez.
- **"Diğer" nedeni**: `is_other` işaretli neden seçildiğinde açıklama
  zorunludur. Girilen açıklamalar en az 10 karakter olmalıdır.
- **Otomatik kayıt**: İptal edilen aşama, iptal eden kullanıcı ve
  iptal tarihi sistem tarafından kaydedilir; iptal özeti chatter'a
  yazılır.
- **PO üzerinde gösterim**: İptal bilgileri mevcut "Diğer Bilgiler"
  sekmesinde koşullu "İptal Bilgileri" grubunda görüntülenir; iptal
  edilmemiş siparişlerde grup gizlidir. Taslağa alınan siparişte
  iptal bilgileri temizlenir.
- **İptal Analizi**: Satınalma > Raporlama > İptal Analizi altında
  iptal edilen sipariş adedi ve toplam tutar; neden, aşama,
  kullanıcı, tedarikçi ve tarih (gün/hafta/ay/çeyrek/yıl)
  kırılımlarında pivot, grafik ve liste olarak analiz edilebilir.
  "Diğer" nedenli kayıtlar ayrıca filtrelenebilir.

## Yetkiler

- İptal nedenleri okuma: tüm Satınalma kullanıcıları.
- İptal nedenleri yönetimi ve İptal Analizi menüsü: Satınalma
  Yöneticisi (`purchase.group_purchase_manager`).

## Dağıtım Notu

Modül Python modelleri içerdiği için Uygulamalar > İçe Aktarma
Modülü ile yüklenemez (base_import_module yalnızca data/static/i18n
ayıklar; yeni modellerin ir.model kayıtları oluşmadığından ACL csv
hata verir). Klasör addons path'e konup normal şekilde kurulmalıdır.

## Başlangıç Verileri

Modül BRD'ye uygun sekiz nedenle gelir: İhtiyaç ortadan kalktı,
Fiyat uygun bulunmadı, Tedarikçi kaynaklı, Yanlış sipariş
oluşturuldu, Mükerrer sipariş, Alternatif tedarikçiden satın
alındı, Talep sahibi iptal etti ve Diğer (açıklama zorunlu).
