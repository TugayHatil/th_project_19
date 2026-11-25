# Sale Order Forecast Nature

Satış siparişlerine **Sipariş Niteliği** (`order_nature`) alanı ekler:
`Kesin` ve `Öngörü`.

## Akış

- Teklif aşamasında alan **boş** kalır; teklif nitelik seçilmeden
  kaydedilebilir ve gönderilebilir.
- **Onayla** butonu niteliksiz teklifte doğrudan onay yapmaz; "Sipariş
  Niteliğini Seçiniz" penceresi açılır (Kesin / Öngörü yan yana butonlar,
  varsayılan seçim yok). Pencere kapatılırsa sipariş teklif durumunda kalır.
- **Kesin** seçilirse standart onay + teslimat akışı çalışır.
- **Öngörü** seçilirse sipariş `sale` durumuna geçer ancak teslimat emri,
  stok hareketi ve rezervasyon **oluşturulmaz** (tedarik kuralı
  `_action_launch_stock_rule` satır bazında engellenir).
- Formda nitelik önceden seçilmişse Onayla doğrudan çalışır.
- **Portal, online ödeme, webhook, XML-RPC ve cron** gibi arayüz dışı
  onaylarda pencere açılamaz; sipariş otomatik **Kesin** niteliği alır.
  Arayüz çağrısı `/web/` yolu üzerinden tespit edilir.
- Entegrasyonlar `order.with_context(order_nature='forecast')` ile
  niteliği önden iletebilir.

## Aktarım (Kesin siparişe dönüştürme)

- Onaylanmış Öngörü siparişinin satır listesinde **Aktar** onay kutusu ve
  **Aktarım** miktarı kolonu görünür (yalnızca Öngörü niteliğinde;
  teklifte ve Kesin siparişlerde gizlidir). Satır işaretlendiğinde Aktarım
  varsayılan olarak kalan miktarla dolar; boş/0 bırakılırsa kalanın
  tamamı aktarılır.
- **Kesin Siparişe Dönüştür** butonu işaretli satırları **yeni bir Kesin
  siparişe** taşır: başlık bilgileri kopyalanır, satırlar aktarım
  miktarlarıyla oluşturulur, sipariş otomatik onaylanır ve standart
  teslimat/stok süreci başlar. Kaynak Öngörü siparişi yerinde kalır.
- Aktarım **parçalıdır**: her satırda `Aktarılan` ve `Kalan` miktar
  izlenir; kalan miktarlar sonraki dönüştürmelerde yeni Kesin siparişlere
  aktarılabilir. Aktarım miktarı kalanı aşamaz.
- Öngörü siparişindeki **Kesin Siparişler** akıllı butonu oluşan
  siparişleri listeler; Kesin siparişteki **Öngörü Siparişi** butonu
  kaynağa döner. Bağlantılar `forecast_order_id` ve
  `forecast_source_line_id` alanlarıyla tutulur, her iki tarafın
  chatter'ına işlem yazılır.
- `was_confirmed` bayrağı onaylanmış siparişin niteliğini kilitler;
  onaylı/iptal siparişlerde nitelik `write` ile değiştirilemez (sunucu
  tarafı kontrol).
- İptal edilen sipariş teklife döndürüldüğünde `order_nature`,
  `forecast_converted`, `was_confirmed` ve satır işaretleri sıfırlanır;
  yeniden onayda seçim penceresi tekrar açılır.

## Faturalama

- Öngörü siparişlerde `qty_to_invoice` sıfırlanır (durum "Faturalandırılacak
  Bir Şey Yok") ve `_create_invoices` sunucu tarafında engellenir;
  yüzdeli avans faturası butonu da gizlenir. Aktarılan Kesin siparişlerde
  standart faturalama çalışır.

## Görünümler

- Liste görünümünde nitelik pastel badge olarak gösterilir (Kesin yeşil,
  Öngörü turuncu); aramada "Kesin" / "Öngörü" filtreleri ve
  "Sipariş Niteliği" gruplaması bulunur.

Bağımlılık: `sale_stock`

Yeni menü veya model oluşturulmaz; `sale_order_type_journal` benzeri
ticari sınıflandırma alanlarından bağımsız çalışır.
