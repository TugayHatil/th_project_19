# Supplier Document Expiry

Tedarikçi belgelerinin merkezi kaydı ve geçerlilik takibi. Belge
türü başına sarı/turuncu uyarı günü tanımlanır; günlük cron durumu
(yeşil/sarı/turuncu/kırmızı) günceller ve seviye değişiminde
sorumluya aktivite üretir.

Üç yetki seviyesi: Okuma (dosya indiremez), Kullanıcı, Yönetici.

Bağımlılık: `purchase`, `mail`
