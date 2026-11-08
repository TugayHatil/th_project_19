# UAT Raporu — `sale_tender` (İhale Yönetimi)

| | |
|---|---|
| **Tarih** | 08.11.2026 |
| **Ortam** | https://demo19.odoobulut.com (Odoo 19 Enterprise) |
| **Modül Sürümü** | 19.0.1.5.0 (installed) |
| **Test Aracı** | `uat_sale_tender.py` — JSON-RPC tabanlı otomatik UAT |
| **Sonuç** | **27/27 PASS** |

## Test Senaryoları ve Sonuçlar

### Kurulum & Yapılandırma

| # | Kontrol | Sonuç |
|---|---------|-------|
| 1 | `sale_tender` modülü kurulu (19.0.1.5.0) | PASS |
| 2 | Gruplar mevcut: İhale Kullanıcısı / İhale Yöneticisi | PASS |
| 3 | "İhale" `sale.order.type` kaydı oluştu | PASS |
| 4 | Kayıt nedenleri seed edildi (5 adet) | PASS |
| 5 | Menü: Satış > Siparişler > İhaleler | PASS |
| 6 | Menü: Satış > Yapılandırma > İhale Kayıt Nedenleri | PASS |

### İhale Kaydı

| # | Kontrol | Sonuç |
|---|---------|-------|
| 7 | `display_name` = "İhale No - İhale Adı" | PASS |
| 8 | Rakip (res.partner) etiket olarak bağlanabiliyor | PASS |
| 9 | Aşama geçişi: Hazırlık → Teklif Verildi | PASS |
| 10 | Aşama geçişi: Teklif Verildi → Kazanıldı | PASS |
| 11 | Kaybedildi: nedensiz write reddedilir (ValidationError) | PASS |
| 12 | `action_set_lost` kayıt nedeni wizard'ını açıyor | PASS |
| 13 | Wizard onayı: state=lost + lost_reason_id set | PASS |
| 14 | Kaybedildi'den çıkınca neden otomatik temizlenir | PASS |

### Teklif Entegrasyonu

| # | Kontrol | Sonuç |
|---|---------|-------|
| 15 | Teklif Oluştur: partner/so_type/tender/user default'ları | PASS |
| 16 | `sale_order_count` = 1 (teklif bağlandıktan sonra) | PASS |
| 17 | Smart button domain + `active_test: False` context | PASS |
| 18 | Satış türü=İhale iken ihale alanı zorunlu | PASS |
| 19 | Başka müşterinin ihalesi seçilemez (ValidationError) | PASS |
| 20 | İhale türü olmayan teklifte ihale zorunlu değil | PASS |
| 21 | Revizyon (copy): so_type_id + tender_id korunur | PASS |
| 22 | Arşivli (iptal) revizyon sayaca dahil (count=2) | PASS |

### Kısıtlar & Yetkilendirme

| # | Kontrol | Sonuç |
|---|---------|-------|
| 23 | Bağlı teklifi olan ihale silinemez (UserError) | PASS |
| 24 | Teklifsiz ihale silinebilir | PASS |
| 25 | ACL: İhale Kullanıcısı salt okunur (read only) | PASS |
| 26 | ACL: İhale Yöneticisi tam yetki (r/w/c/d) | PASS |

### Rapor (PDF Çıktı)

| # | Kontrol | Sonuç |
|---|---------|-------|
| 27 | İhale PDF'i hatasız render ediliyor (~28 KB) | PASS |

## Kapsam Dışı / Manuel Doğrulanan

- Statusbar tıklanabilirliği (arayüzde doğrulandı, `options clickable` ile)
- Form görsel hizalaması (Ek Bilgiler grup başlığı ile çözüldü)
- Chatter üzerinden doküman ekleme (standart mail.thread)

## Notlar

- `latest_version` alanı modül listesi yenilenmeden eski sürümü gösterebilir; `installed_version` doğru değeri verir.
- UAT script tekrar çalıştırılabilir; her koşuda zaman damgalı test kayıtları oluşturur.
