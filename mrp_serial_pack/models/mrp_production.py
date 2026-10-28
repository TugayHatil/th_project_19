# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command


BOX_CAPACITY = 5
PALLET_CAPACITY = 10


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    pack_transfer_qty = fields.Integer(
        string="Aktarılacak Miktar", copy=False,
        help="Veri Al ile hazırlanması istenen toplam hedef miktar. "
             "Önceki aktarıma eklenecek miktarı değil, toplam hedefi ifade "
             "eder. Boş bırakılırsa planlanan üretim miktarı kullanılır.")
    pack_package_ids = fields.One2many(
        "stock.package", "production_id", string="Packages", copy=False)
    pack_box_count = fields.Integer(
        compute="_compute_pack_counts", compute_sudo=True)
    pack_pallet_count = fields.Integer(
        compute="_compute_pack_counts", compute_sudo=True)

    @api.depends("pack_package_ids", "pack_package_ids.package_type_id")
    def _compute_pack_counts(self):
        box_type = self._get_box_package_type()
        pallet_type = self._get_pallet_package_type()
        for production in self:
            packages = production.pack_package_ids
            production.pack_box_count = len(packages.filtered(
                lambda p: p.package_type_id == box_type))
            production.pack_pallet_count = len(packages.filtered(
                lambda p: p.package_type_id == pallet_type))

    @api.constrains("pack_transfer_qty")
    def _check_pack_transfer_qty(self):
        for production in self:
            if production.pack_transfer_qty and production.pack_transfer_qty <= 0:
                raise ValidationError(_(
                    "Aktarılacak Miktar pozitif bir tam sayı olmalıdır."))

    # ------------------------------------------------------------------
    # Paket türleri
    # ------------------------------------------------------------------

    def _get_box_package_type(self):
        return self.env.ref(
            "mrp_serial_pack.package_type_box", raise_if_not_found=False) \
            or self.env["stock.package.type"].search(
                [("name", "=", "Koli")], limit=1)

    def _get_pallet_package_type(self):
        return self.env.ref(
            "mrp_serial_pack.package_type_pallet", raise_if_not_found=False) \
            or self.env["stock.package.type"].search(
                [("name", "=", "Palet")], limit=1)

    # ------------------------------------------------------------------
    # Veri Al
    # ------------------------------------------------------------------

    def action_fetch_data(self):
        """"Veri Al" butonu.

        Üretim emrini tamamlamadan, hedef miktara ulaşacak kadar seri
        numarası, koli ve palet kaydı hazırlar. Seri numaraları standart
        ``lot_producing_ids`` üzerinden üretim emrine bağlanır; üretim
        hareket satırları ``result_package_id`` ile kolilere, koliler
        ``package_dest_id`` üzerinden paletlere bağlanır. Üretim
        tamamlanırken seriler hareket satırlarına standart akışla yazılır
        ve koli->palet bağı gerçek paket hiyerarşisine dönüşür.
        """
        self.ensure_one()
        self._check_fetch_data_allowed()
        # Aynı üretim emrinde eş zamanlı Veri Al işlemlerini sıraya al.
        self.env.cr.execute(
            "SELECT id FROM mrp_production WHERE id = %s FOR UPDATE",
            (self.id,))

        finished_move = self.move_finished_ids.filtered(
            lambda m: m.product_id == self.product_id
            and m.state != "cancel")[:1]
        if not finished_move:
            raise UserError(_(
                "Bu üretim emrinde üretilecek ürün için tamamlanmamış bir "
                "üretim hareketi bulunamadı."))

        target = self._get_pack_target_qty()
        prepared = self._get_prepared_pack_qty(finished_move)
        if target <= prepared:
            message = _(
                "Bu üretim emri için %(prepared)s adet zaten hazırlanmış "
                "durumda; yeni hedef (%(target)s) bu değerin üzerinde "
                "olmadığı için yeni seri, koli veya palet oluşturulmadı. "
                "Mevcut kayıtlar korundu.",
                prepared=int(prepared), target=int(target))
            self.message_post(body=message)
            return self._pack_notification(message, notif_type="warning")

        missing = target - prepared
        previous_boxes = self._get_pack_packages("box")
        previous_pallets = self._get_pack_packages("pallet")

        lots = self._prepare_serial_lots(missing)
        self.lot_producing_ids = [Command.link(lot.id) for lot in lots]
        self.qty_producing = self.product_id.uom_id._compute_quantity(
            target, self.product_uom_id, rounding_method="HALF-UP")
        self.set_qty_producing()

        # `set_qty_producing` eksik adet kadar yeni, paketsiz hareket satırı
        # oluşturur; paketlenmiş satırlara dokunmaz. Lotsuz satırları kolilere
        # yerleştir. Seriler satıra bilinçli olarak YAZILMAZ: üretim serisi
        # bir hareket satırında görünürse standart `_check_sn_uniqueness`
        # "zaten üretilmiş" hatası verir; seri-satır eşleşmesi üretim
        # tamamlanırken `move.lot_ids` üzerinden standart akışla yapılır.
        lines_to_pack = finished_move.move_line_ids.filtered(
            lambda ml: ml.state not in ("done", "cancel")
            and ml.quantity > 0 and not ml.result_package_id
            and not ml.lot_id and not ml.lot_name
        ).sorted("id")
        for move_line in lines_to_pack:
            move_line.result_package_id = self._get_or_create_pack_box()

        new_boxes = self._get_pack_packages("box") - previous_boxes
        new_pallets = self._get_pack_packages("pallet") - previous_pallets
        message = _(
            "%(new)s adet hazırlandı. Toplam: %(total)s seri, "
            "%(boxes)s koli, %(pallets)s palet "
            "(bu işlemde %(new_boxes)s koli, %(new_pallets)s palet "
            "oluşturuldu). Üretim emri henüz tamamlanmadı.",
            new=int(missing), total=int(target),
            boxes=len(self._get_pack_packages("box")),
            pallets=len(self._get_pack_packages("pallet")),
            new_boxes=len(new_boxes), new_pallets=len(new_pallets))
        self.message_post(body=message)
        return self._pack_notification(message)

    def _check_fetch_data_allowed(self):
        self.ensure_one()
        if self.state not in ("confirmed", "progress", "to_close"):
            raise UserError(_(
                "Veri Al yalnızca onaylanmış ve tamamlanmamış üretim "
                "emirlerinde kullanılabilir (geçerli durum: %(state)s).",
                state=dict(self._fields["state"]._description_selection(
                    self.env)).get(self.state, self.state)))
        if self.product_tracking != "serial":
            raise UserError(_(
                "Veri Al yalnızca seri numarasıyla takip edilen ürünlerde "
                "kullanılabilir."))

    def _get_pack_target_qty(self):
        """Veri Al hedefi: kullanıcı toplam hedefi girdiyse o, yoksa
        planlanan üretim miktarı (ürün biriminde, tam sayı)."""
        self.ensure_one()
        planned = self.product_uom_id._compute_quantity(
            self.product_qty, self.product_id.uom_id,
            rounding_method="HALF-UP")
        target = float(self.pack_transfer_qty or 0) or planned
        if target <= 0 or target != int(target):
            raise UserError(_(
                "Aktarılacak Miktar pozitif bir tam sayı olmalıdır."))
        if target > planned:
            raise UserError(_(
                "Aktarılacak Miktar (%(target)s) planlanan üretim "
                "miktarını (%(planned)s) aşamaz.",
                target=int(target), planned=int(planned)))
        return int(target)

    def _get_prepared_pack_qty(self, finished_move):
        """Şu ana kadar hazırlanmış üretim adedi.

        Üretim emrine ``lot_producing_ids`` ile bağlanmış seri sayısı;
        standart "Serial Numbers" sayacı ile aynı kaynaktır.
        """
        self.ensure_one()
        return len(self.lot_producing_ids)

    def _prepare_serial_lots(self, count):
        """Üretime bağlanacak ``count`` adet seri numarası hazırlar.

        Şimdiki sürümde seri numaraları Odoo içerisinde, ürünün standart
        seri numarası yapılandırmasıyla (``_prepare_stock_lot_values``)
        üretilir. SQL ara görünümü hazırlandığında yalnızca bu veri
        kaynağı değişecektir; koli/palet iş kuralları etkilenmez.
        """
        self.ensure_one()
        Lot = self.env["stock.lot"]
        lots = Lot
        for _i in range(int(count)):
            lots |= Lot.create(self._prepare_stock_lot_values())
        return lots

    # ------------------------------------------------------------------
    # Koli / palet seçimi ve oluşturma
    # ------------------------------------------------------------------

    def _get_pack_packages(self, kind):
        package_type = (self._get_box_package_type() if kind == "box"
                        else self._get_pallet_package_type())
        return self.pack_package_ids.filtered(
            lambda p: p.package_type_id == package_type)

    def _get_or_create_pack_box(self):
        """Kapasitesi dolmamış en eski koliyi döndürür; yoksa yeni koli
        oluşturup uygun bir palete bağlar."""
        self.ensure_one()
        for box in self._get_pack_packages("box").sorted("id"):
            if box._get_pack_fill(self.product_id) < BOX_CAPACITY:
                if not box.package_dest_id and not box.parent_package_id:
                    box.package_dest_id = self._get_or_create_pack_pallet()
                return box
        return self.env["stock.package"].create({
            "package_type_id": self._get_box_package_type().id,
            "production_id": self.id,
            "package_dest_id": self._get_or_create_pack_pallet().id,
        })

    def _get_or_create_pack_pallet(self):
        """Kapasitesi dolmamış en eski paleti döndürür; yoksa yeni palet
        oluşturur."""
        self.ensure_one()
        for pallet in self._get_pack_packages("pallet").sorted("id"):
            children = pallet.child_package_ids | pallet.child_package_dest_ids
            if len(children) < PALLET_CAPACITY:
                return pallet
        return self.env["stock.package"].create({
            "package_type_id": self._get_pallet_package_type().id,
            "production_id": self.id,
        })

    # ------------------------------------------------------------------
    # Görünüm aksiyonları ve bildirim
    # ------------------------------------------------------------------

    def _pack_notification(self, message, notif_type="success"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Veri Al"),
                "type": notif_type,
                "message": message,
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_view_pack_boxes(self):
        return self._action_view_pack_packages("box")

    def action_view_pack_pallets(self):
        return self._action_view_pack_packages("pallet")

    def _action_view_pack_packages(self, kind):
        self.ensure_one()
        package_type = (self._get_box_package_type() if kind == "box"
                        else self._get_pallet_package_type())
        return {
            "type": "ir.actions.act_window",
            "name": _("Koliler") if kind == "box" else _("Paletler"),
            "res_model": "stock.package",
            "view_mode": "list,form",
            "domain": [
                ("production_id", "=", self.id),
                ("package_type_id", "=", package_type.id),
            ],
        }
