# Sale Order Forecast Nature

Satış siparişlerine **Sipariş Niteliği** (`order_nature`) alanı ekler:
`Kesinleşmiş` ve `Öngörü`.

- **Öngörü** teklifler standart onay süreciyle Satış Siparişi durumuna
  gelir; sipariş numarası oluşur ancak teslimat emri, stok hareketi ve
  rezervasyon **oluşturulmaz** (tedarik kuralı `_action_launch_stock_rule`
  satır bazında engellenir).
- Onaylanmış Öngörü siparişi formundaki **Kesinleşmiş Siparişe Dönüştür**
  butonu (onay pencereli) siparişi aynı numara ve satırlarla Kesinleşmiş
  niteliğe çevirir ve standart teslimat sürecini başlatır. İşlem
  chatter'a yazılır, tek yönlüdür ve her sipariş için bir kez yapılabilir.
- Kilitli (`locked`) siparişlerde kural çalıştırılırken kilit geçici
  kaldırılıp geri yüklenir.
- Dönüştürülmüş sipariş `forecast_converted` bayrağı ile işaretlenir;
  iptal → taslak döngüsüyle bile tekrar Öngörü yapılamaz. Onaylı/iptal
  siparişlerde nitelik `write` ile değiştirilemez (sunucu tarafı kontrol).
- Öngörü siparişlerde `qty_to_invoice` sıfırlanır (durum "Faturalandırılacak
  Bir Şey Yok") ve `_create_invoices` sunucu tarafında engellenir;
  yüzdeli avans faturası butonu da gizlenir.
- Liste görünümünde nitelik pastel badge olarak gösterilir (Kesinleşmiş
  yeşil, Öngörü turuncu); aramaya "Öngörü" filtresi ve
  "Sipariş Niteliği" gruplaması eklenir.

Bağımlılık: `sale_stock`

Yeni menü veya model oluşturulmaz; `sale_order_type_journal` benzeri
ticari sınıflandırma alanlarından bağımsız çalışır.
