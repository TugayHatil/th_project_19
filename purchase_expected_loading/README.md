# Purchase Expected Loading Date

Satınalma siparişine sevk türü (Denizyolu, Havayolu, Karayolu, Demiryolu)
ve beklenen yükleme tarihi ekler.

- **Diğer Bilgiler** sekmesinde **Sevk Türü** alanı.
- Başlıkta, Beklenen Geliş'in hemen üzerinde **Beklenen Yükleme**; sipariş
  satırlarında da aynı alan (beklenen geliş mantığıyla: başlıktan satırlara
  uygulanır, satırda değiştirilen değer geçerlidir).
- Tedarikçi fiyat listesi (`product.supplierinfo`) satırında sevk türü başına
  transit süre (gün) tablosu; dört sevk türü otomatik oluşturulur.
- Siparişte sevk türü seçildiğinde her satırın beklenen yükleme tarihi
  `beklenen geliş - transit süre` olarak otomatik hesaplanır.
- Beklenen yükleme tarihi transfer (stok hareketi) satırlarına da taşınır;
  planlanan tarih gibi çalışır.

Bağımlılık: `purchase_stock`
