# th_project_19

Odoo 19 addon collection.

## `crm_second_currency`

Adds a second (deal) currency to CRM opportunities next to the company
currency: the user picks the deal currency and enters the amount in it
(Revenue Other Currency); the system converts it through the exchange
rate and writes the result into the standard Expected Revenue field in
company currency. Prorated Revenue (Other Currency) shows the
probability-weighted share of the second-currency amount. Both
second-currency amounts are also displayed on the CRM kanban card.

## `mrp_component_alternative`

Defines alternative materials on BOM component lines (priority + active flag),
shows an icon on replenishment lines whose product has alternatives, and lets
users pick & confirm a substitute component on manufacturing orders when the
main component is short (system suggests the first alternative that fully
covers the demand; selection is applied to the component move and reservation).

## `mrp_purchase_need_plan`

Material Need Planning screen (Manufacturing → Planning → Material Need
Planning). Groups open manufacturing component demands by product, shows
each need date on its own row with on-hand stock, chronological forecast
balance, purchase-start and approve-by dates (supplier lead time +
purchase process days from the product card or the Purchase settings
default), and merges the uncovered needs of the selected product groups
into a single `purchase.request` per company. Source moves stay linked
to the request line (`need_move_ids`) for traceability and duplicate
protection.

## `project_critical_path`

Calculates every maximum-duration dependency chain in an Odoo Project using
standard `project.task` dependencies and each task's allocated time.

## `product_extra_fields`

Extends the product card (`product.template`) with extra classification,
responsibility, storage, quality control and purchasing fields: Old Material
No, Material Group, External Material Group, Validity Start date, MIP No +
related MIP responsible, Production Supervisor No + related supervisor,
production / external procurement storage locations, production & purchase
quality-inspection flags, purchase quantity rounding and purchase group
(Direct/Indirect). Ships four central definition models (Material Groups,
External Material Groups, MIP Responsibles, Production Supervisors) managed
under Inventory → Configuration → Products; changing the responsible on a
definition record automatically updates every linked product card.

## `sale_order_forecast`

Adds an Order Nature (Sipariş Niteliği) selection on sale orders: Kesin
or Öngörü. The field stays empty on quotations; pressing Confirm opens a
selection dialog (Kesin / Öngörü) and orders cannot reach the `sale` state
without a nature. Öngörü orders confirm to Sales Order without creating
delivery orders, stock moves or reservations. A confirmed Öngörü order can be
converted in place to Kesin from a header button (with confirmation dialog):
the same order number and lines are kept, the standard stock-rule/delivery
flow is launched and the conversion is logged to chatter. Conversion is
one-way and can only happen once (tracked via `forecast_converted`, enforced
server-side). Öngörü orders cannot be invoiced (`qty_to_invoice` forced to
zero plus a `_create_invoices` guard) until converted. Works independently
of the Sale Order Type field and does not touch stock forecast, reservation
or MRP mechanics.

## `sale_tender`

İhale Yönetimi: adds a Tender Management menu under Sales with a
standalone `sale.tender` model (tender number, name, customer, dates,
tracked state Hazırlık → Teklif Verildi → Kazanıldı/Kaybedildi/İptal,
responsible, description, document attachments). A **Teklifler** smart
button lists linked sale orders; **Teklif Oluştur** opens the standard
quotation form with customer, Sale Type (İhale), tender and responsible
pre-filled. `sale.order` gains a **Satış Türü** selection (Yurtiçi /
Yurtdışı / İhale / Bedelsiz / Diğer) and an **İhale** many2one filtered
to the customer's tenders and required when the type is İhale. Both
fields copy on revision, tenders with linked orders cannot be deleted,
and two groups (İhale Kullanıcısı read-only, İhale Yöneticisi full)
govern access.
