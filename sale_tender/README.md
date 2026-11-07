# İhale Yönetimi (Sale Tender)

Centralized tracking of customer tenders linked to sale quotations.

Adds a **Tender Management** menu under Sales. Each tender record holds
the tender number, name, customer, tender date, bid deadline, state
(Hazırlık / Teklif Verildi / Kazanıldı / Kaybedildi / İptal — tracked in
chatter), responsible user, description and document attachments.

The tender form shows a **Teklifler** smart button listing all linked
sale orders (number, customer, order date, sale type, amount, currency,
state) and a **Teklif Oluştur** header button that opens the standard
quotation form with customer, sale type (İhale), tender and responsible
pre-filled.

`sale.order` gains two fields:

- **Satış Türü** — Yurtiçi Satış, Yurtdışı Satış, İhale, Bedelsiz, Diğer
- **İhale** — many2one to `sale.tender`, filtered to the customer's
  tenders and required when Sale Type is İhale

Both fields are copied on revision, so revised quotations keep the
tender link. Tenders with linked sale orders cannot be deleted.

## Security

- **İhale Kullanıcısı**: read-only access to tenders; can open linked
  quotations via the smart button. Implies the "all sale orders" sales
  group.
- **İhale Yöneticisi**: full create/write/delete on tenders, can create
  quotations from a tender. Implies İhale Kullanıcısı.

A multi-company record rule scopes tenders to the active companies.
