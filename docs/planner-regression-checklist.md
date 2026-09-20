# Planner Regression Checklist (v1)

Her release/deploy öncesi çalıştırılır. Otomatik: `odoo-bin -d <db> -u project_critical_path --test-enable --test-tags /project_critical_path`. Manuel maddeler MCP/browser üzerinden gerçek kullanıcı davranışıyla yapılır.

**Referans dataset:** `Planner UI Test` (id=3) — detay: `docs/planner-certification-v1.md`.

## Otomatik (backend + tour)

- [ ] `test_critical_path.py` — CPM, cascade, lag, rollup, inspector save
- [ ] `test_planner_certification.py` — parallel max, SS/FF/SF, FS+10h, payload
- [ ] `test_planner_tour.py` — açılış, day sürekliliği, Inspector, ölçek geçişleri

## Manuel sertifikasyon (≈20 madde)

### Açılış & Navigasyon
- [ ] 1. Planner hard refresh ile açılıyor; `scrollLeft=0`'da takılmıyor.
- [ ] 2. Timeline ilk görevin bulunduğu bölgeye odaklanıyor (bar viewport'ta).
- [ ] 3. WBS paneli + başlıklar render; header ↔ bar hizası doğru.
- [ ] 4. Date picker ileri (örn. 15 Ara) ve geri (örn. 15 Tem) doğru tarihe iniyor.
- [ ] 5. `Bugün` butonu today marker'ı viewport'a getiriyor.

### Zoom (− / + / Fit)
- [ ] Z1. `+` saat/gün kolonlarını görünür şekilde genişletiyor; `−` sıkıştırıyor.
- [ ] Z2. Anchor preservation: zoom sonrası viewport merkezindeki tarih/saat yerinde kalıyor.
- [ ] Z3. Min/max sınırda butonlar güvenli (disabled veya no-op); NaN/Infinity yok.
- [ ] Z4. `Fit` proje aralığını viewport'a sığdırıyor; ölçek (Day/Week/Month) değişmiyor.
- [ ] Z5. Ölçek geçişi zoom seviyesini koruyor; zoom sonrası scroll/drag/resize/oklar/baseline doğru.

### Continuous Timeline
- [ ] 6. Day: `23:00 → 00:00 → 01:00` kesintisiz; gün grupları art arda.
- [ ] 7. Sağ kenara scroll → buffer genişliyor, viewport sıçramıyor.
- [ ] 8. Sol kenara scroll → aralık sola açılıyor, içerik sabit (telafi doğru).
- [ ] 9. Week/Month geçişlerinde bar pozisyonu ve saat hassasiyeti korunuyor.

### Drag / Resize
- [ ] 10. Görev sürükleme persist oluyor (gece yarısı aşımı dahil, saat hassas).
- [ ] 11. Sağ kenarda auto-scroll ≥30 sn: tooltip ↔ bar senkron, lag yok.
- [ ] 12. Sol kenarda auto-scroll: aralık genişliyor, task pointer'ı takip ediyor.
- [ ] 13. Sağ grip resize persist; `allocated_hours` güncelleniyor; edge'de auto-scroll çalışıyor.

### Scheduling
- [ ] 14. `2.3`'ü ileri taşı → zincir cascade (`2.4→…→3.4`), ilgisiz görevler kımıldamıyor.
- [ ] 15. `2.3 → 2.4 FS +10h`: 2.4 tam `2.3.finish + 10h`'de (gün aşımı dahil).
- [ ] 16. `3.3` parallel predecessor: `max(2.4, 3.2.3)` bound'una oturuyor.
- [ ] 17. Critical Path: drag/cascade sonrası kritik flag'ler + slack doğru (~15 kritik).

### Rollup / Baseline / Inspector
- [ ] 18. Child taşı → parent `min(start)/max(end)`; parent dep edge'i olsa bile ezilmiyor; büyük-parent'a bubble.
- [ ] 19. Baseline ghost bar'lar + variance tooltip'leri scroll/genişleme/refresh'te doğru.
- [ ] 20. Inspector: tarih+saat+duration değiştir → Kaydet → persist; atanmamış görevde `date_assign` silinmiyor.
- [ ] 21. Dependency okları başlangıç/sağ-sol scroll/genişleme sonrası bar'lardan kopmuyor.
- [ ] 22. Hard refresh sonrası tüm değerler (tarih, saat, allocated, dep, baseline, CP, rollup) korunuyor.
- [ ] 23. Console'da yeni JS exception yok (bilinen `web_gantt`/`crm_komtas_ux` hataları hariç).

**PASS kriteri:** tüm otomatik testler yeşil + maddeler 1–23 işaretli. Kritik kombinasyon (Long Timeline + Buffer + Auto-scroll + Drag + Dependency + Cascade + CP) tek akışta doğrulanmalı.
