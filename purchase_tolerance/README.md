# Purchase Tolerance

Genel ayar, ürün ve PO satırı seviyesinde fazla teslimat toleransı.
Mal kabul doğrulamasında toleransı aşan satırlar için onay talebi
(`purchase.tolerance.request`) açılır; Satınalma Yöneticisi
onaylarsa satır toleransı güncellenir, aksi halde doğrulama
engellenir.

Talepler: Satınalma > Siparişler > Tolerans Talepleri.
Yalnızca talep sahibi kendi talebini görür; satınalma ekibi tümünü
görür.

Bağımlılık: `purchase_stock`
