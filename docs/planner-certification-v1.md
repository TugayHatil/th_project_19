# Planner v1 Certification

## Genel Bilgiler

| Alan | Değer |
|---|---|
| Planner Version | **v1 Stable** |
| Modül | `project_critical_path` (Odoo 19) |
| Test yöntemi | MCP Browser UI (gerçek kullanıcı davranışı) + backend TransactionCase + web tour |
| Test ortamı | `https://demo19.projet.solutions` — kullanıcı `tugay` |
| Test tarihi | 2026-09-20 |
| Branch | `main` |
| Son stabil commit | `2a20899` — *Planner: keep planned dates when Inspector saves an unassigned task* |

## Test Özeti

| Metrik | Değer |
|---|---|
| UI Senaryosu | 35+ |
| Regression Turu | 3+ |
| Bulunan Bug | 8 |
| Düzeltilen Bug | 8 |
| Final Durum | **PASS** |

Kritik kombinasyon doğrulandı: **Long Timeline + Buffer Expansion + Auto-scroll + Drag + Dependency + Cascade + Critical Path — PASS.**

## Sertifikalanan Özellikler

- **Continuous Timeline** — `rangeStart`/`rangeEnd` tabanlı, görev aralığı + ölçek buffer'ı ile kesintisiz kolonlar; başlık, bar, dependency SVG, baseline ve today marker aynı koordinat sistemini paylaşır.
- **Day / Week / Month** — Gün görünümü `23:00 → 00:00 → 01:00` saat sürekliliği; Hafta ISO hafta numarası; Ay takvim ayı ve doğru gün sayısı (Şubat 2027 = 28).
- **Horizontal Scroll & Buffer Expansion** — Kenarlara yaklaşınca aralık iki yönde de büyür; sol genişlemede scroll telafisi viewport'u sabit tutar.
- **Drag & Drop** — Gün ölçeğinde saat hassasiyetiyle taşıma; tooltip bar'la senkron (`_colsCache` + gerçek scroll delta'sı).
- **Auto-scroll** — Pointer kenara yakınken kontrollü hız (~300 px/s); sağ ve sol kenarlarda çalışır; 30 sn'lik tutuşta lag birikmez.
- **Resize** — Sol/sağ grip'ler; edge'de auto-scroll ile uzatma; `allocated_hours` senkronu.
- **Dependency (FS/SS/FF/SF)** — Dört ilişki tipi edge attribute olarak saklanır ve ok üzerinde lag etiketiyle çizilir.
- **Lag** — Saat/gün birimli lag; `FS +10h` gece yarısını geçen örnekte bile tam sınırda.
- **Automatic Cascade Scheduling** — `_schedule_dependents` değişen görev + downstream'i topolojik sırada saat hassasiyetiyle ileri iter; ihlal yoksa dokunmaz.
- **Parallel Predecessor** — Birden çok predecessor'u olan görev `max()` bound kullanır; erken predecessor'ın hareketi ardılı gereksiz kaydırmaz.
- **Critical Path** — Erken/geç geçişler, slack ve `is_critical` flag'leri her yazışta yeniden hesaplanır (test projesinde 15 kritik görev).
- **Parent Rollup** — Parent window = `min(children.start)` / `max(children.end)`; cascade parent'ı ezmez (WBS parent'lar shift'ten muaftır).
- **Baseline & Variance** — Ghost bar'lar snapshot koordinatında; variance tooltip'leri doğru; genişleme/refresh'te korunur.
- **Inspector Save** — Tarih + saat input'ları dt hassasiyetiyle persist olur; atanmamış görevde `date_assign` korunur.
- **WBS** — Hiyerarşik kodlar ve sıralama timeline işlemlerinden etkilenmez; sticky panel.
- **Refresh Persistence** — Hard refresh sonrası tarih/saat/allocated/dependency/baseline/CP/rollup tamamen korunur.
- **Localization** — Başlıklar, ay/gün isimleri ve UI metinleri aktif Odoo diline uyar.

## Bulunan ve Düzeltilen Bug'lar

| Commit | Bug | Kök neden |
|---|---|---|
| `b11fb46` | Inspector Save sessizce başarısız | `saveInspector` içinde TDZ `ReferenceError` |
| `90152a2` | Parent tarihleri güncellenmiyor | Child write parent window'u senkronlamıyordu |
| `b3948fd` | Yetkisiz kullanıcıda sessiz revert | `check_access_rights`/`canEdit` eksikti |
| `a2e32ca` | Açılış/nav scroll clamp | `scrollToDate` render'dan önce koşuyordu |
| `7509d0b` | Drag render lag + kenar taşması | Her tick'te ~2300 kolon yeniden üretimi + `extraDx` clamp'siz delta |
| `14eccbc` | Açılış görevlerin öncesine odaklıyordu | Odak snap'lenmiş periyot başıydı |
| `d14984c` | Geriye nav yanlış tarihe iniyordu | Sol genişleme telafisi nav'da çift uygulanıyordu |
| `335d08d` | Parent rollup cascade tarafından eziliyordu | `_schedule_dependents` parent'ı kendi dep bound'una itiyordu |
| `2a20899` | Inspector save `date_assign`'i siliyordu | Native Odoo `write()` boş `user_ids`'te assigning date'i temizler |

*(Bazı bug'lar aynı regression turunda birden fazla kez sayılabilir; düzeltme sayısı 8+ commit.)*

## Bilinen Düşük Öncelikli Riskler

- Çok yıllık **Day** aralıkları binlerce saat kolonu üretir — timeline virtualization gelecekte değerlendirilebilir.
- Parent görevlerde legacy `depend_on` edge'leri bulunabilir; BRD-25 uyarınca yeni parent-level dependency oluşturulmamalı (edge'ler leaf'lere yönlendirilir).
- Headless/test ortamında FPS ölçümü rAF throttling nedeniyle belirsizdir; gerçek tarayıcıda akıcı gözlemlendi.
- Ortamda mevcut `web_gantt`/`crm_komtas_ux` asset hataları Planner'ı etkilemiyor (ortamsal).

## Referans Test Dataset

**Proje:** `Planner UI Test` (id=3) — regression için referans veri seti.

- **23 görev** — WBS: `1, 1.1, 1.2, 1.2.1, 1.2.2, 1.3, 2, 2.1–2.4, 3, 3.1, 3.2, 3.2.1–3.2.3, 3.3, 3.4, 4, 4.1–4.3`
- **18 dependency edge** — zincir: `2.3 → 2.4 → 3.1 → 3.2.1 → 3.2.2 → 3.2.3 → 3.3 → 3.4`
- **Parallel predecessor** — `3.3` hem `2.4` hem `3.2.3`'e bağlı (max bound)
- **Lag örneği** — `2.3 → 2.4 FS +10h`
- **Parent+dep edge** — `1.2 → 1.1` (rollup↔cascade regresyon senaryosu)
- **Baseline** — "Başlangıç Noktası v1.0" snapshot'ı (23 ghost bar + variance)
- **Critical Path** — 15 kritik leaf görev

## Otomatik Test Haritası

| Katman | Dosya | Kapsam |
|---|---|---|
| Backend (TransactionCase) | `tests/test_critical_path.py` | CPM, cascade, lag, rollup, inspector save |
| Backend (TransactionCase) | `tests/test_planner_certification.py` | v1 sertifikasyon: parallel max, SS/FF/SF, FS+10h gün aşımı, payload kontratı, inspector gün yolu |
| Backend | `tests/test_planner_workspace.py` | WBS sıralama, planner data API |
| Frontend (web tour) | `tests/test_planner_tour.py` + `static/tests/tours/planner_workspace_tour.js` | Açılış, day sürekliliği, WBS→Inspector, dep okları, today, ölçek geçişleri |
| Manuel (MCP UI) | `docs/planner-regression-checklist.md` | Drag, auto-scroll, resize — birebir otomatikleştirilemeyen gerçek-pointer senaryoları |

Çalıştırma:

```bash
odoo-bin -d <db> -u project_critical_path --test-enable \
  --test-tags /project_critical_path --stop-after-init
```
