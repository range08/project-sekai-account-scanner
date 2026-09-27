"""Normalize material and currency quantities."""

from __future__ import annotations

from typing import Any

from pjsk_scanner.master.repository import MasterDataRepository
from pjsk_scanner.models import MaterialProgress
from pjsk_scanner.normalize.fields import int_field, rows


def normalize_materials(
    payload: dict[str, Any], master: MasterDataRepository
) -> list[MaterialProgress]:
    materials: list[MaterialProgress] = []
    for index, row in enumerate(rows(payload, "userMaterials")):
        context = f"userMaterials[{index}]"
        material_id = int_field(row, "materialId", context, required=True)
        assert material_id is not None
        item = master.material(material_id)
        materials.append(
            MaterialProgress(
                material_id=material_id,
                name=item.name if item else None,
                material_type=item.material_type if item else None,
                quantity=int_field(row, "quantity", context),
            )
        )
    return materials
