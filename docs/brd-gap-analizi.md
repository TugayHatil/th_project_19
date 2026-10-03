# BRD Gap Analizi — Project Execution & Control

> Kaynak BRD: "PROJECT EXECUTION & CONTROL — Business Requirements &
> Development Specification". Mevcut kod: `project_critical_path` v19.0.9.0.0
> + `project_resource_planning` v19.0.1.0.0 (bkz. `teknik-dokumantasyon.md`).
> Durum: **✅ var / 🟡 kısmen / ❌ yok**

---

## 1. Yapısal Karar: Nereye?

BRD'nin "mevcut fonksiyonlar korunacak + mümkünse inheritance" kuralıyla
uyumlu olarak üçüncü bir addon önerilir:

```
project_critical_path  ◄──  project_resource_planning  ◄──  project_execution_control
```

- Yeni addon `project_execution_control`: `depends =
  ["project_resource_planning", "hr_skills", "analytic"]` (hr_skills
  community'de mevcut; analytic zaten timesheet zincirinde gelir).
- Çekirdek ve kaynak addon'a **dokunulmadan** tüm yeni modeller/alanlar
  inheritance ile eklenir — mevcut hook mimarisi (`_planner_resource_fields`,
  `_get_planner_resource_data`, `_get_baseline_resource_vals`…) aynı
  desende genişletilir.
- Planner payload'a yeni anahtarlar eklenirken çekirdekte boş-default
  kalması için gerekiyorsa çekirdeğe **tek satırlık yeni hook** eklemek
  kabul edilebilir (davranış değişmez).

BRD §2.1'de listelenen "Material Requirement", "Capacity Planning / Work
Center" bu iki addonda **mevcut değil** — `mrp_long_term_planning` /
`aos_construction_management` addon'larına ait olabilir veya BRD genel
yazılmış. Geliştirme öncesi netleştirilmeli.

---

## 2. Bölüm Bölüm Gap Analizi

### §4 Actual / Gerçekleşen Takibi

| BRD İsteği | Mevcut Durum | Yapılacak |
|---|---|---|
| Planned Start/End/Duration | ✅ `date_assign`, `date_deadline`, `allocated_hours` | — |
| Planned Effort | ✅ `allocated_hours` | — |
| Actual Effort | ✅ `effective_hours` (hr_timesheet) — zaten WBS rollup'ında ve planner bar-info'da kullanılıyor | — |
| Completion % | ✅ `progress` + `progress_rollup` | — |
| Actual End | 🟡 `date_done` var (state→done damgası, readonly) | Manuel girilebilir alanla birleştir: `date_actual_end` (veya `date_done`'u editable yap) |
| Actual Start | ❌ yok | `date_actual_start` (Datetime, editable) + ilk timesheet'ten fallback önerisi opsiyonel |
| Actual Duration | ❌ | compute: `_task_window_hours` konvansiyonu (aynı gün = saat farkı, çok gün = gün × hours_per_day) veya takvim `get_work_hours_count` — BRD "mevcut calendar mantığını kullan" diyor |
| Schedule Variance | 🟡 `finish_variance_state` (late/early/on_time, **takvim günü** bazlı) + `delay_duration_variance` (saat) zaten var | Gün farkı alanı ekle (`actual_end − planned_end`, gün); mevcut selection ile tutarlı tut |
| Actual status | ❌ | `actual_status` compute: `not_started / in_progress / done` (start girilmiş mi + state) |
| Gantt'ta actual bar | ❌ | Planner payload'a `dt_actual_start`, `date_actual_end` ekle; `date_done` zaten payload'da — üçüncü bar katmanı (baseline ghost + plan + actual) |
| Actual yoksa bar yok / task başlamadıysa boş | — | Alanlar boşken UI'da render edilmez |

**Constraint (§28):** `date_actual_end < date_actual_start` → ValidationError;
end var start yoksa da engel/uyarı.

### §5 Project Actual Summary

| KPI | Kaynak |
|---|---|
| Total/Completed/InProgress/NotStarted | `state` + `date_actual_start` sayımı — `search_count` yerine tek `_read_group` |
| Project Completion % | Root WBS `progress_rollup` (saat-ağırlıklı mevcut mantık — BRD'nin istediği "mevcut ağırlıklandırmayı kullan" kuralı) |
| Planned/Actual Duration | `critical_path_duration` / fiili açıklık = `max(date_actual_end) − min(date_actual_start)` |
| Delayed Task Count | `finish_variance_state == 'late'` + overdue domain (`date_deadline < today, state != done`) |
| Critical Delayed | aynısı + `is_critical` |

Hepsi proje üzerinde compute — dashboard ile ortak hesap servisi.

### §6–7 Material Delay & Risk

Mevcut zemin güçlü: `project.material.plan` → `move_ids` → `stock.move`.

| Veri | Kaynak |
|---|---|
| Required Qty | ✅ `planned_quantity` |
| Required Date | ✅ `required_date` |
| Available Qty | `move_ids` üzerinden: `move.state` + `forecast_availability`/`quantity`; draft satır için `product.free_qty` (lokasyonlu) — BRD "availability yoksa 'available' gösterme" kuralı: move yoksa `unknown` durumu |
| Expected Availability | `move.forecast_expected_date` (Odoo 19'da var) → yoksa `move.date`/`picking.scheduled_date` |
| Shortage | `max(0, planned − available)` |
| Material Delay Days | `max(0, expected_avail − required_date)` gün |

**Görev etkisi:** task'a `material_risk` compute Selection:
`none / partial / delay / critical_delay` (kritik = `is_critical` veya delay
> slack). Planner payload'a `material_risk` alanı + liste/Gantt rozeti.

**Downstream & proje etkisi (§6.5–6.6):** Mevcut `_get_task_dependency_graph`
+ slack değerleri yeniden kullanılır. **Projeksiyon, plan değişikliği
değil**: mevcut `_recalculate_delay_impacts` matematiğine paralel olarak —
`task_delay = material_delay_gün × hours_per_day`; proje etkisi ≈
`min(max(0, task_delay − slack), toplam)`; etkilenen downstream zinciri
mevcut `_get_delay_impact_chain` mantığıyla metinleştirilir. Gerçek
tarihleri kaydırmaz — "what-if" gösterir.

### §8–11 Skill & Competency

| BRD | Çözüm |
|---|---|
| Skill master | `hr_skills` → `hr.skill`, `hr.skill.type`, `hr.skill.level`, `hr.employee.skill` — **yeni skill sistemi yazılmaz** (BRD açıkça bunu istiyor) |
| Valid From/Until + Certificate ref | `hr.employee.skill`'e küçük extension (mixin addon içinde) veya sertifika için `hr.certification`/belge alanı — hr_skills'in `display_type`/seviye modeli korunur |
| Task required skills | Yeni model `project.task.skill.requirement` (task_id, skill_id [veya skill_type_id + min_level]) — requirement'tan bağımsız çünkü rol≠skill |
| Matching (§10) | Assignment create/employee change'de **soft check**: `skill_mismatch` compute alanı + `_check_...` → `Warning` değil, `ValidationError` yerine mismatch flag + UI uyarısı (BRD "hard-block olmak zorunda değil") |
| Availability (§11) | ✅ `project.resource.planner` zaten calendar bazlı availability hesaplıyor — aynı servis `skill_mismatch` ile birleştirilir |

### §12–17 Cost

| Tür | Planned | Actual |
|---|---|---|
| Labor | ✅ `requirement.planned_cost` (rate snapshot) | `Σ timesheet.unit_amount × employee.hourly_cost` (hr_timesheet `hourly_cost` alanı) — task'ın `timesheet_ids`'inden tek `_read_group` |
| Material | ✅ `material_plan.planned_cost` | done `stock.move` satırları: `Σ move.quantity × product.standard_price` (tüketim = gerçekleşen move; "hayali consumption yok" kuralına uygun) |
| Other | ❌ | `project.cost.line` (veya `account.analytic.line` proje hesabı) — minimal model: project_id, task_id, type, amount, description |

- Variance: `actual − planned`, `variance_% = ... / planned * 100`,
  planned=0 → `%` = `False` (division-safe).
- Project Cost Summary (§17): tip bazında planned/actual/variance —
  compute veya `project.cost.summary` transient; `_read_group` batch.

### §18–23 Change Request

❌ Tamamen yeni — `project.change.request`:

- Alanlar: `name` (sequence ref), `project_id`, `task_id` (aynı proje
  constrain), `title`, `description`, `requested_by_id`, `request_date`,
  `reason`, `type` (scope/schedule/cost/resource/material/other),
  `priority`, `state` (draft→submitted→approved/rejected→implemented),
  `approval_date`, `approved_by_id`.
- Impact alanları: `schedule_impact_days`, `cost_impact`, `effort_impact`,
  `material_impact_note`/`line`.
- Workflow metotları: `action_submit / action_approve / action_reject /
  action_apply_change` — approve sadece project manager (BRD §27).
- Audit trail: `mail.thread` + `mail.activity` inherit (`_track_`)
  — "history" için hazır Odoo mekanizması, yeni log modeli gereksiz.
- `action_apply_change`: **açık buton**, etkilenen alanları task'a uygular
  (ör. `allocated_hours += effort_impact`, `date_deadline += days`);
  `state → implemented`, `applied_on` damgası. Baseline'a **asla
  dokunmaz** — baseline zaten model seviyesinde immutable (§2.6 mevcut).
  Uygulama `project_id` eşleşmesi constrain'li.

### §24 Dashboard — Project Control Summary

Proje formuna **"Project Control"** notebook sayfası: compute KPI alanları
(Schedule/Material/Resource/Cost/Change blokları). Hesaplar merkezi
`_compute_control_summary()` altında, `_read_group` batch — N+1 yok.
İstersen bağımsız menü/dashboard view da aynı compute'u kullanır.

### §25 Filters

`project_task_planner_search` + task search inherit: `material_risk`,
`skill_mismatch`, `cost_overrun` (compute alanlar → **store=True** şart,
yoksa domain'de kullanılamaz), `has_open_change_request`, actual status
filtreleri (delayed/critical/completed/in-progress/not-started — bir kısmı
zaten var).

### §26 Gantt Entegrasyonu

- Planner workspace'e actual bar katmanı + material risk rozeti +
  change-request sayısı — `planner_workspace_resource.js` deseninde ayrı
  patch dosyası (`planner_workspace_control.js`).
- Payload genişletme: çekirdeğe boş-hook prensibiyle yeni
  `_planner_control_fields()` → task başına actual/risk/mismatch/cost.
- Mevcut bar/ghost/drag davranışına dokunulmaz.

### §27 Security

| BRD Rolü | Eşleşme |
|---|---|
| Project User | `base.group_user` + mevcut modellerde CRUD; actual alan girişi → guard'a `date_actual_*` **eklenmez** (fiili veri girişi serbest kalmalı) veya ayrı "actual entry" grubu — **karar noktası** |
| Project Manager | `project.group_project_manager` → CR approve, maliyet görünürlüğü, skill yönetimi |
| Project Administrator | `group_planner_manager` veya admin grup — yapılandırma |

Yeni modellere ir.model.access.csv: CR ve skill requirement'lara user
read + manager write deseni.

### §28 Data Integrity — karşılanma durumu

| Kural | Durum |
|---|---|
| Actual Start > End engeli | eklenecek constrain |
| Negatif duration | compute `max(0,…)` |
| Planned=0 → % güvenli | `False` dön |
| Actual yoksa duration yok | compute boş |
| Availability bilinmiyorsa "available" değil | `unknown` durumu |
| Skill req yoksa mismatch yok | mismatch sadece req varken hesaplanır |
| CR başka projeye uygulanamaz | `task_id.project_id == project_id` constrain |
| Baseline değişmez | ✅ zaten model-seviye korumalı |

### §29 Performance

Mevcut desen aynen sürdürülür: `_read_group` batch toplamalar, store'lu
compute'lar (filtre/rapor alanları), tek-geçiş project aggregation,
değişmeyen satır UPDATE edilmez kuralı. Dashboard KPI'ları compute
alanı olarak (form açılışında hesaplanır) — çok projeli listede ağır
olursa ayrı sayfa/servis çağrısı yapılabilir.

---

## 3. Önerilen Implementasyon Fazları

| Faz | Kapsam | Bağımlılık |
|---|---|---|
| **F1 — Actual Tracking** | `date_actual_start/end`, `actual_duration`, `actual_status`, schedule variance gün alanı, proje summary KPI'ları, planner actual bar + payload, filtreler | yok |
| **F2 — Material Delay & Impact** | availability/shortage/expected-date computes, `material_risk`, delay gün hesabı, downstream/projeksiyon (dependency graph + slack reuse), risk badge | F1 değil |
| **F3 — Skill Matching** | `hr_skills` dep, `project.task.skill.requirement`, employee skill validity ext., `skill_mismatch` compute + assignment warning + planner entegrasyonu | yok |
| **F4 — Cost Control** | actual labor (timesheet×hourly_cost), actual material (done moves), other cost line, variance %, project cost summary | F1'e yakın ama bağımsız |
| **F5 — Change Request** | `project.change.request` + workflow + mail.thread audit + `action_apply_change` + security | F1 (actual/plan ayrımı iyi olur ama şart değil) |
| **F6 — Dashboard & Filters & Gantt** | Control sayfası, yeni filtreler, planner patch (actual bar, risk, mismatch) | F1–F5 çıktılarını tüketir |
| **F7 — Hardening** | Security detayları, testler (ACT/MAT/SKL/COST/CR setleri), regression turu | tüm fazlar |

Her faz sonunda: kendi testleri + mevcut 16 test dosyasının regression
koşusu (BRD §36 zorunlu kılıyor).

## 4. Karar Noktaları (geliştirme öncesi netleşmeli)

1. **"Material Requirement" / "Capacity Planning / Work Center"** — BRD
   korumalı listesinde ama bu iki addonda yok; `mrp_long_term_planning` /
   `aos_construction_management` mı kastediliyor?
2. **Actual entry yetkisi** — `date_actual_*` planner guard'ına girsin mi
   (sadece manager) yoksa saha kullanıcısı da girebilsin mi?
3. **Skill mismatch hard-block mu warning mi** — BRD warning öneriyor;
   constraint yerine compute-flag + görsel uyarı önerilir.
4. **"Other Cost" kaynağı** — manuel `project.cost.line` mı, yoksa proje
   analytic hesabındaki `account.analytic.line` mı? (İkincisi faturalama
   entegrasyonu verir.)
5. **Change Request "Apply" kapsamı** — BRD sadece "task/dependency/date/
   cost güncellenebilir" diyor; somut apply haritası (hangi impact alanı →
   hangi task alanı) tek tek netleştirilecek.
6. **Certificate validity** — `hr_skills`'te hazır validity yok; custom
   `hr.employee.skill` extension mı, `hr.appraisal`/belge mi?
7. **Yeni addon adı** — `project_execution_control` önerisi.

---

*Hazırlanma: 2026-10-03 · Kaynak: kod analizi + BRD §1–40*
