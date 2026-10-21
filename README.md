# th_project_19

Odoo 19 addon collection.

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
