# th_project_19

Odoo 19 addon collection.

## `mrp_component_alternative`

Defines alternative materials on BOM component lines (priority + active flag),
shows an icon on replenishment lines whose product has alternatives, and lets
users pick & confirm a substitute component on manufacturing orders when the
main component is short (system suggests the first alternative that fully
covers the demand; selection is applied to the component move and reservation).

## `project_critical_path`

Calculates every maximum-duration dependency chain in an Odoo Project using
standard `project.task` dependencies and each task's allocated time.
