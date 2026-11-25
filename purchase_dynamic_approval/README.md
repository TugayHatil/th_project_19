# Purchase Dynamic Approval

Satınalma siparişinin toplam tutarına göre hangi kullanıcı gruplarının
onaylayacağını belirleyen barem bazlı kademeli onay akışı. Sipariş,
tutarının denk geldiği bareme kadar alttaki tüm baremlerin gruplarından
sırasıyla onay geçer. Standart "Onay Bekliyor" durumu üzerinden
çalışır; barem başına opsiyonel vekil onaycı, zorunlu red nedeni,
onay geçmişi ve tutar değişikliğinde yeniden değerlendirme içerir.

Baremler Satınalma > Yapılandırma > Onay Baremleri altında
yönetilir. Örnek baremler pasif gelir.

Bağımlılık: `purchase`
