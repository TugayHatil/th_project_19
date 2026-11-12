# Purchase Request Line Paste

Satınalma talebi (`purchase.request`) satır listesinde "Satır Ekle"nin
yanına, taslak durumdayken görünen **Satır Yapıştır** bağlantısı ekler
(`<control>` butonu — `purchase.order`'daki Catalog deseni). Bağlantı,
Excel'den kopyalanan "ürün kodu + miktar" listesini alan bir sihirbaz açar:

- Her satır `ürün kodu <sekme> miktar` biçimindedir (`;` ve boşluk da
  desteklenir); ilk satır başlıksa otomatik atlanır.
- **Önizle** adımı her satırı doğrular: ürün `default_code` ile çözümlenir
  (`purchase_ok` olmayan veya birden fazla eşleşen kodlar hata sayılır),
  miktar kullanıcının Odoo dil/biçim ayarına göre ayrıştırılır
  (örn. tr_TR için `1.234,5`).
- **Satırları Ekle** yalnızca geçerli satırları `purchase.request.line`
  olarak oluşturur; ürün onchange'inin ürettiği `name`, `product_uom_id`
  değerleri birebir uygulanır. Hatalı satırlar atlanır ve önizleme
  listesinde işaretli kalır; işlem talebin chatter'ına özetlenir.
- Aynı ürün birden fazla kez geçerse manuel girişteki gibi ayrı satırlar
  oluşur.

Bağımlılık: `purchase_request`
