# Purchase Dynamic Approval

Satınalma siparişinin toplam tutarına göre hangi kullanıcı gruplarının
onaylayacağını belirleyen barem bazlı kademeli onay akışı. Direkt
Alım ve Endirekt Alım için ayrı barem setleri tanımlanır; siparişin
hangi akışa gireceği, satırlardaki satınalma grubu tanımlı ilk
üründen gelen "Satınalma Grubu" alanıyla belirlenir. Sipariş, kendi
akışında tutarının denk geldiği bareme kadar alttaki tüm baremlerin
gruplarından sırasıyla onay geçer. Standart "Onay Bekliyor" durumu
üzerinden çalışır; barem başına opsiyonel vekil onaycı, zorunlu red
nedeni, onay geçmişi ve tutar/satınalma grubu değişikliğinde yeniden
değerlendirme içerir.

Baremler Satınalma > Yapılandırma > Onay Baremleri altında
yönetilir. Örnek baremler pasif gelir.

Bağımlılık: `purchase`, `product_extra_fields`
