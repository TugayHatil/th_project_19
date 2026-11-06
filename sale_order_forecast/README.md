# Sale Order Forecast Nature

Satış siparişlerine **Sipariş Niteliği** (`order_nature`) alanı ekler:
`Normal` ve `Forecast`.

- **Forecast** teklifler standart onay süreciyle Satış Siparişi durumuna
  gelir; sipariş numarası oluşur ancak teslimat emri, stok hareketi ve
  rezervasyon **oluşturulmaz** (tedarik kuralı `_action_launch_stock_rule`
  satır bazında engellenir).
- Onaylanmış Forecast siparişi formundaki **Normal Siparişe Dönüştür**
  butonu (onay pencereli) siparişi aynı numara ve satırlarla Normal
  niteliğe çevirir ve standart teslimat sürecini başlatır. İşlem
  chatter'a yazılır, tek yönlüdür ve her sipariş için bir kez yapılabilir.
- Kilitli (`locked`) siparişlerde kural çalıştırılırken kilit geçici
  kaldırılıp geri yüklenir.
- Dönüştürülmüş sipariş `forecast_converted` bayrağı ile işaretlenir;
  iptal → taslak döngüsüyle bile tekrar Forecast yapılamaz. Onaylı/iptal
  siparişlerde nitelik `write` ile değiştirilemez (sunucu tarafı kontrol).
- Forecast siparişlerde `qty_to_invoice` sıfırlanır (durum "Faturalandırılacak
  Bir Şey Yok") ve `_create_invoices` sunucu tarafında engellenir;
  yüzdeli avans faturası butonu da gizlenir.
- Liste görünümüne opsiyonel sütun, aramaya "Forecast" filtresi ve
  "Sipariş Niteliği" gruplaması eklenir.

Bağımlılık: `sale_stock`

Yeni menü veya model oluşturulmaz; `sale_order_type_journal` benzeri
ticari sınıflandırma alanlarından bağımsız çalışır.
