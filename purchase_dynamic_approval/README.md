# Purchase Dynamic Approval

Satınalma siparişlerinde toplam tutara göre farklı kullanıcı gruplarının
onayını gerektiren dinamik, parametrik onay mekanizması.

## Özellikler

- **Onay Baremleri**: Satınalma > Yapılandırma > Onay Baremleri
  altında (veya Satınalma ayarlarından) sınırsız sayıda tutar aralığı
  tanımlanabilir. Her barem için Sıra, Alt Tutar, Üst Tutar (veya
  Sınırsız), Onaylayıcı Grup ve Aktif/Pasif alanları bulunur.
- **Çakışma kontrolü**: Alt sınır dahil, üst sınır hariç mantığıyla
  aralıklar birbiriyle çakışamaz; aynı aralık tekrar tanımlanamaz,
  birden fazla sınırsız üst sınır olamaz.
- **Standart akış korunur**: Yeni PO state'i eklenmez; onay standart
  `to approve` (Onay Bekliyor) durumunda yürütülür.
- **Grup üyeliği yetkisi**: Yalnızca baremde tanımlı gruba üye
  kullanıcılar Onayla / Reddet yapabilir. Grupta tek kişinin onayı
  yeterlidir; siparişi oluşturan kullanıcı ilgili gruptaysa kendi
  siparişini de onaylayabilir.
- **Onay Geçmişi**: PO üzerindeki "Onay" sekmesinde tüm işlemler
  (gönderim, onay, red, barem/tutar değişikliği, taslağa alma)
  tarih, kullanıcı, grup ve açıklama ile saklanır; silinemez.
- **Aktivite**: Onaya gönderimde onaylayıcı grubun tüm aktif üyelerine
  aktivite atanır; onay/red ile kapatılır. İşlemler chatter'a yazılır.
- **Tutar değişikliği**: Onay bekleyen PO'da tutar değişirse barem
  yeniden hesaplanır; farklı bareme geçilirse onay süreci yeni grup
  için yeniden başlatılır, barem kalmazsa sipariş otomatik onaylanır.
- **Red nedeni zorunludur** ve serbest metin yerine Yapılandırma >
  Red Nedenleri altında yönetilen hazır seçeneklerden seçilir.

## Rol: Onay Barem Yöneticisi

`Onay Barem Yöneticisi` grubu baremleri oluşturabilir, düzenleyebilir,
silebilir ve aktif/pasif yapabilir. Grup, Satınalma Yöneticisi
yetkisini de içerir.

Modül, BRD örneğine uygun dört örnek barem ve üç örnek onaylayıcı
grupla gelir (Satınalma Uzmanları, Satınalma Müdürleri, Genel
Müdürleri); hepsi düzenlenebilir veya silinebilir.
