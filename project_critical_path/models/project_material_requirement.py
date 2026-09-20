# -*- coding: utf-8 -*-

from odoo import _, fields, models


class ProjectMaterialRequirement(models.Model):
    """Material Requirement (BRD phase 2): the stock-availability view of a
    project's Material Plan.

    This is a SQL view, not a snapshot table: rows are derived live from
    ``project.material.plan`` aggregated per (Project, Product) and joined to
    ``stock_quant`` availability. A plan edit or a stock change is reflected
    on the next read — no cron, no duplicate data, no manual refresh button.

    ``shortage_quantity``/``status`` are real view columns so the standard
    list Filters and Group By work natively on them, and the status is
    inherently read-only (nobody can write to a view).
    """

    _name = "project.material.requirement"
    _description = "Project Material Requirement"
    _auto = False
    _order = "required_date, product_id, id"

    project_id = fields.Many2one(
        "project.project", string="Project", readonly=True,
    )
    product_id = fields.Many2one(
        "product.product", string="Product", readonly=True,
    )
    uom_id = fields.Many2one(
        "uom.uom", string="UoM", readonly=True,
    )
    # Earliest required date across the source lines — per-line dates are
    # preserved on material_plan_line_ids.
    required_date = fields.Date(string="Required Date", readonly=True)
    planned_quantity = fields.Float(string="Planned Quantity", readonly=True)
    # Available = on-hand minus reserved over internal locations, in the
    # product's own UoM — Odoo's `free_qty` semantics taken straight from
    # stock_quant so the number is always live stock data.
    available_quantity = fields.Float(string="Available Quantity", readonly=True)
    shortage_quantity = fields.Float(string="Shortage Quantity", readonly=True)
    status = fields.Selection(
        [
            ("not_available", "Not Available"),
            ("partially_available", "Partially Available"),
            ("available", "Available"),
        ],
        string="Status", readonly=True,
    )
    company_id = fields.Many2one(
        "res.company", string="Company", readonly=True,
    )
    material_plan_line_ids = fields.Many2many(
        "project.material.plan", string="Source Material Plan Lines",
        compute="_compute_material_plan_line_ids",
    )

    def _compute_display_name(self):
        for requirement in self:
            requirement.display_name = (
                requirement.product_id.display_name or _("Material Requirement")
            )

    def _compute_material_plan_line_ids(self):
        Plan = self.env["project.material.plan"]
        for requirement in self:
            requirement.material_plan_line_ids = Plan.search([
                ("project_id", "=", requirement.project_id.id),
                ("product_id", "=", requirement.product_id.id),
            ])

    def init(self):
        self.env.cr.execute('DROP VIEW IF EXISTS "%s"' % self._table)
        # Quantities are aggregated in the product's own UoM: each plan line
        # is converted via uom_uom.factor (absolute factor to the UoM family
        # root). Lines whose UoM belongs to a different family are kept raw —
        # the plan UI already restricts the choice to the product's family.
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    req.id AS id,
                    req.project_id AS project_id,
                    req.product_id AS product_id,
                    req.uom_id AS uom_id,
                    req.required_date AS required_date,
                    req.company_id AS company_id,
                    req.planned_quantity AS planned_quantity,
                    req.available_quantity AS available_quantity,
                    req.shortage_quantity AS shortage_quantity,
                    CASE
                        WHEN req.shortage_quantity >= req.planned_quantity
                            THEN 'not_available'
                        WHEN req.shortage_quantity > 0
                            THEN 'partially_available'
                        ELSE 'available'
                    END AS status
                FROM (
                    SELECT
                        MIN(p.id) AS id,
                        p.project_id AS project_id,
                        p.product_id AS product_id,
                        pt.uom_id AS uom_id,
                        MIN(p.required_date) AS required_date,
                        MIN(p.company_id) AS company_id,
                        SUM(
                            CASE
                                WHEN ptu.factor <> 0
                                     AND split_part(pu.parent_path, '/', 1)
                                         = split_part(ptu.parent_path, '/', 1)
                                THEN p.planned_quantity * pu.factor / ptu.factor
                                ELSE p.planned_quantity
                            END
                        ) AS planned_quantity,
                        GREATEST(
                            SUM(
                                CASE
                                    WHEN ptu.factor <> 0
                                         AND split_part(pu.parent_path, '/', 1)
                                             = split_part(ptu.parent_path, '/', 1)
                                    THEN p.planned_quantity * pu.factor / ptu.factor
                                    ELSE p.planned_quantity
                                END
                            ) - COALESCE(av.qty, 0),
                            0
                        ) AS shortage_quantity,
                        COALESCE(av.qty, 0) AS available_quantity
                    FROM project_material_plan p
                    JOIN product_product pp ON pp.id = p.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    JOIN uom_uom pu ON pu.id = p.uom_id
                    JOIN uom_uom ptu ON ptu.id = pt.uom_id
                    LEFT JOIN (
                        SELECT sq.product_id AS product_id,
                               SUM(sq.quantity - sq.reserved_quantity) AS qty
                        FROM stock_quant sq
                        JOIN stock_location sl ON sl.id = sq.location_id
                        WHERE sl.usage = 'internal'
                        GROUP BY sq.product_id
                    ) av ON av.product_id = p.product_id
                    GROUP BY p.project_id, p.product_id, pt.uom_id, av.qty
                ) req
            )
        """ % self._table)
