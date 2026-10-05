# Product Multi Manufacturer

Odoo 19 addon that links products to multiple manufacturers, each with its own
manufacturer code, note and status.

## Features

- **Üreticiler** tab on the product form (template and variant) with a
  One2many list of manufacturer records.
- New `product.manufacturer` model: `product_id`, `manufacturer_code`,
  `manufacturer_id`, `note`, `state` (statusbar-driven).
- `res.partner.is_manufacturer` flag on the contact form (after `ref`);
  only contacts flagged as manufacturers can be selected.
- Central menu: **Inventory → Products → Üretici Kodları** listing all
  manufacturer records across products.
- SQL constraint prevents duplicate `product + manufacturer + code`
  combinations.
- Security: internal users get read-only access; the
  **Üretici Kodları Yönetimi** group (assigned to nobody by default) grants
  full create/write/delete rights.

## Structure

```
product_multi_manufacturer/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── product_manufacturer.py
│   ├── product_product.py
│   ├── product_template.py
│   └── res_partner.py
├── views/
│   ├── product_manufacturer_views.xml
│   ├── product_product_views.xml
│   ├── product_template_views.xml
│   └── res_partner_views.xml
├── security/
│   ├── ir.model.access.csv
│   └── security.xml
└── README.md
```
