# purchase_tolerance

Satınalma toleransı ve fazla teslimat yönetimi (Odoo 19).

## Özellikler

- **Genel ayar**: Satınalma → Yapılandırma → Ayarlar altında
  "Varsayılan Satınalma Toleransı (%)".
- **Ürün toleransı**: Ürün kartının Satınalma sekmesinde ürüne özel
  tolerans tanımlanabilir (varsayılanı kullan seçeneği ile).
- **PO satırı toleransı**: Sipariş oluşturulurken ürün/genel ayardan
  otomatik dolar; yalnızca Satınalma Yöneticisi değiştirebilir.
  PO onaylandıktan sonra da değiştirilebilir ve değişiklikler
  chatter'a yazılır.
- **Mal kabul kontrolü**: Transfer doğrulamasında (Validate) önceki
  kısmi teslimatlar dahil kümülatif tolerans kontrolü yapılır.
  İade hareketleri ve iç adımlar hesaba katılmaz.
- **Tolerans aşımı talebi**: Aşım durumunda depo kullanıcısına talep
  oluşturma sihirbazı açılır. Talep (`purchase.tolerance.request`)
  satınalma sorumlusuna activity ile iletilir.
- **Onay/Red**: Satınalma Yöneticisi talebi onaylarsa PO satırı
  toleransı güncellenir ve mal kabul yapılabilir; reddederse mevcut
  tolerans korunur.

## Menü

Satınalma → Siparişler → Tolerans Talepleri

## Yetkiler

| Rol | Talep Görüntüle | Talep Oluştur | Tolerans Değiştir | Onay/Red |
| --- | --- | --- | --- | --- |
| Depo Kullanıcısı | Kendi talepleri | Evet | Hayır | Hayır |
| Satınalma Kullanıcısı | Tümü | Evet | Hayır | Hayır |
| Satınalma Yöneticisi | Tümü | Evet | Evet | Evet |
