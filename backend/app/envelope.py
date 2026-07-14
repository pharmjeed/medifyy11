"""غلاف الاستجابة الموحد — DOC-05 §١: {data, meta}."""
from __future__ import annotations

from typing import Any


def ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"data": data, "meta": meta or {}}


def paginated(items: list[Any], total: int, page: int, per_page: int) -> dict[str, Any]:
    return {"data": items, "meta": {"total": total, "page": page, "per_page": per_page}}
