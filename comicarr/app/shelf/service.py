#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Print copies on the operator's shelf.

One row per physical book: Cover A and a 1:25 variant of the same issue are two
copies. A copy points at an issue, an annual, or a manga volume number. Each
copy also keeps a snapshot of its series name, item label and cover, because
removing a series deletes its issue rows and the operator still owns the
books. Adding the series back re-links the copies, since the ids are the
provider's.

A copy is either ``owned`` or on the ``wishlist``. Nothing here changes an
issue's status or what search looks for.
"""

from __future__ import annotations

import datetime
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from sqlalchemy import and_, delete, func, insert, or_, select, update

from comicarr import db
from comicarr.app.manga.ledger import normalize_volume_number
from comicarr.tables import annuals, comics, issues, physical_copies

OWNED = "owned"
WISHLIST = "wishlist"
STATES = (OWNED, WISHLIST)

ISSUE = "issue"
ANNUAL = "annual"
VOLUME = "volume"
ITEM_KINDS = (ISSUE, ANNUAL, VOLUME)

FORMATS = ("single", "tpb", "hc", "omnibus", "tankobon", "other")
GRADE_SERVICES = ("raw", "cgc", "cbcs", "pgx")

# Fields an operator may set on create or update, with their length limits.
_TEXT_LIMITS = {
    "VariantName": 200,
    "VariantImageURL": 2000,
    "Printing": 32,
    "BoughtFrom": 200,
    "Storage": 200,
    "Barcode": 32,
    "Notes": 4000,
}
_EDITABLE = (
    "State",
    "VariantName",
    "VariantImageURL",
    "Printing",
    "Format",
    "GradeService",
    "Grade",
    "PaidCents",
    "EstimateCents",
    "Currency",
    "BoughtOn",
    "BoughtFrom",
    "Storage",
    "Barcode",
    "Notes",
)
_MAX_CENTS = 100_000_000_00  # one hundred million in any currency
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_BARCODE = re.compile(r"^[0-9]{8,17}$|^[0-9]{9}[0-9X]$")
_URL = re.compile(r"^https?://", re.IGNORECASE)

_CONTENT_MANGA = "manga"
_BOOK_FORMATS = {"TPB": "tpb", "GN": "tpb", "HC": "hc", "Omnibus": "omnibus"}


class CopyError(ValueError):
    """A request the shelf refuses. ``code`` is stable; the UI translates it."""

    def __init__(self, code: str, field: str | None = None, status: int = 400):
        super().__init__(code if field is None else "%s:%s" % (code, field))
        self.code = code
        self.field = field
        self.status = status

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"detail": self.code, "code": self.code}
        if self.field:
            body["field"] = self.field
        return body


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# --- validation --------------------------------------------------------------


def _clean_text(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CopyError("invalid_field", name)
    text = value.strip()
    if not text:
        return None
    if len(text) > _TEXT_LIMITS[name]:
        raise CopyError("field_too_long", name)
    return text


def _clean_choice(name: str, value: Any, choices: Iterable[str]) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value.strip().lower() not in choices:
        raise CopyError("invalid_field", name)
    return value.strip().lower()


def _clean_cents(name: str, value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_CENTS:
        raise CopyError("invalid_field", name)
    return value


def _clean_grade(value: Any) -> str | None:
    """A grade on the 0.5-10 scale, stored as text ("9.4", "10")."""
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise CopyError("invalid_field", "Grade") from None
    if not number.is_finite() or number < Decimal("0.5") or number > Decimal("10"):
        raise CopyError("invalid_field", "Grade")
    return format(number.normalize(), "f")


def _clean_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise CopyError("invalid_field", "BoughtOn")
    try:
        return datetime.date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise CopyError("invalid_field", "BoughtOn") from None


def _clean_fields(body: Mapping[str, Any], *, partial: bool) -> dict[str, Any]:
    unknown = set(body) - set(_EDITABLE) - {"ComicID", "ItemKind", "ItemID", "VolumeNumber"}
    if unknown:
        raise CopyError("unknown_field", sorted(unknown)[0])
    values: dict[str, Any] = {}
    for name in _EDITABLE:
        if name not in body:
            continue
        value = body[name]
        if name == "State":
            state = _clean_choice(name, value, STATES)
            if state is None:
                raise CopyError("invalid_field", name)
            values[name] = state
        elif name == "Format":
            values[name] = _clean_choice(name, value, FORMATS)
        elif name == "GradeService":
            values[name] = _clean_choice(name, value, GRADE_SERVICES)
        elif name == "Grade":
            values[name] = _clean_grade(value)
        elif name in ("PaidCents", "EstimateCents"):
            values[name] = _clean_cents(name, value)
        elif name == "Currency":
            if value is None or value == "":
                values[name] = None
            elif isinstance(value, str) and _CURRENCY.match(value.strip().upper()):
                values[name] = value.strip().upper()
            else:
                raise CopyError("invalid_field", name)
        elif name == "BoughtOn":
            values[name] = _clean_date(value)
        else:
            values[name] = _clean_text(name, value)
    if values.get("Barcode") and not _BARCODE.match(values["Barcode"]):
        raise CopyError("invalid_field", "Barcode")
    if values.get("VariantImageURL") and not _URL.match(values["VariantImageURL"]):
        raise CopyError("invalid_field", "VariantImageURL")
    if not partial and "State" not in values:
        values["State"] = OWNED
    return values


# --- the item a copy points at -------------------------------------------------


def _issue_label(number: Any, name: Any) -> str:
    label = "#%s" % number if number not in (None, "") else ""
    if name:
        return "%s · %s" % (label, name) if label else str(name)
    return label


def _resolve_target(conn, comic_id: Any, item_kind: Any, item_id: Any, volume_number: Any) -> dict[str, Any]:
    """The stored identity and snapshot for a new copy, or CopyError."""
    if not isinstance(comic_id, str) or not comic_id.strip():
        raise CopyError("invalid_field", "ComicID")
    comic_id = comic_id.strip()
    if item_kind not in ITEM_KINDS:
        raise CopyError("invalid_field", "ItemKind")
    series = (
        conn.execute(
            select(comics.c.ComicName, comics.c.ComicImageURL, comics.c.ContentType, comics.c.Type).where(
                comics.c.ComicID == comic_id
            )
        )
        .mappings()
        .first()
    )
    if series is None:
        raise CopyError("series_not_found", status=404)
    target: dict[str, Any] = {
        "ComicID": comic_id,
        "ItemKind": item_kind,
        "ItemID": None,
        "VolumeNumber": None,
        "SeriesName": series["ComicName"],
        "CoverURL": series["ComicImageURL"],
        "DefaultFormat": _BOOK_FORMATS.get(series["Type"] or "", "single"),
    }
    if item_kind == VOLUME:
        if (series["ContentType"] or "").lower() != _CONTENT_MANGA:
            raise CopyError("volume_needs_manga", "ItemKind")
        number = normalize_volume_number(volume_number)
        if number is None:
            raise CopyError("invalid_field", "VolumeNumber")
        target["VolumeNumber"] = number
        target["ItemLabel"] = "Vol. %s" % number
        target["DefaultFormat"] = "tankobon"
        return target
    if not isinstance(item_id, str) or not item_id.strip():
        raise CopyError("invalid_field", "ItemID")
    table = issues if item_kind == ISSUE else annuals
    columns = [table.c.Issue_Number, table.c.IssueName]
    if item_kind == ISSUE:
        columns.append(table.c.ImageURL)
    row = (
        conn.execute(select(*columns).where(table.c.IssueID == item_id.strip(), table.c.ComicID == comic_id))
        .mappings()
        .first()
    )
    if row is None:
        raise CopyError("item_not_found", status=404)
    target["ItemID"] = item_id.strip()
    target["ItemLabel"] = _issue_label(row["Issue_Number"], row["IssueName"])
    if row.get("ImageURL"):
        target["CoverURL"] = row["ImageURL"]
    return target


# --- reads -----------------------------------------------------------------------


def _row(record: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(record)
    item["SeriesPresent"] = item.pop("_series_present", None) is not None
    live_name = item.pop("_live_series_name", None)
    if live_name:
        item["SeriesName"] = live_name
    return item


def _select():
    return select(
        physical_copies,
        comics.c.ComicID.label("_series_present"),
        comics.c.ComicName.label("_live_series_name"),
    ).select_from(physical_copies.outerjoin(comics, comics.c.ComicID == physical_copies.c.ComicID))


def get_copy(copy_id: str) -> dict[str, Any] | None:
    with db.get_engine().connect() as conn:
        record = conn.execute(_select().where(physical_copies.c.CopyID == copy_id)).mappings().first()
    return _row(record) if record else None


def list_copies(
    *,
    comic_id: str | None = None,
    state: str | None = None,
    item_kind: str | None = None,
    item_id: str | None = None,
    storage: str | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Copies matching every given filter, newest first, with the total."""
    conditions = []
    if comic_id:
        conditions.append(physical_copies.c.ComicID == comic_id)
    if state:
        if state not in STATES:
            raise CopyError("invalid_field", "state")
        conditions.append(physical_copies.c.State == state)
    if item_kind:
        if item_kind not in ITEM_KINDS:
            raise CopyError("invalid_field", "item_kind")
        conditions.append(physical_copies.c.ItemKind == item_kind)
    if item_id:
        conditions.append(physical_copies.c.ItemID == item_id)
    if storage:
        conditions.append(physical_copies.c.Storage == storage)
    if query:
        pattern = "%%%s%%" % query.strip().lower()
        conditions.append(
            or_(
                func.lower(physical_copies.c.SeriesName).like(pattern),
                func.lower(comics.c.ComicName).like(pattern),
                func.lower(physical_copies.c.ItemLabel).like(pattern),
                func.lower(physical_copies.c.VariantName).like(pattern),
                func.lower(physical_copies.c.Notes).like(pattern),
            )
        )
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    statement = _select()
    count = select(func.count()).select_from(
        physical_copies.outerjoin(comics, comics.c.ComicID == physical_copies.c.ComicID)
    )
    if conditions:
        statement = statement.where(and_(*conditions))
        count = count.where(and_(*conditions))
    statement = (
        statement.order_by(physical_copies.c.created_at.desc(), physical_copies.c.CopyID).limit(limit).offset(offset)
    )
    with db.get_engine().connect() as conn:
        total = conn.execute(count).scalar_one()
        rows = [_row(record) for record in conn.execute(statement).mappings()]
    return {"results": rows, "total": total, "limit": limit, "offset": offset}


def item_key(item_kind: str, item_id: str | None, volume_number: str | None) -> str:
    """The key the series page groups a copy under: ``issue:ID`` or ``volume:N``."""
    if item_kind == VOLUME:
        return "volume:%s" % volume_number
    return "%s:%s" % (item_kind, item_id)


def series_shelf(comic_id: str) -> dict[str, Any]:
    """Per-item counts for one series, for the Shelf column and its header stat."""
    statement = select(
        physical_copies.c.ItemKind,
        physical_copies.c.ItemID,
        physical_copies.c.VolumeNumber,
        physical_copies.c.State,
        physical_copies.c.PaidCents,
        physical_copies.c.Currency,
    ).where(physical_copies.c.ComicID == comic_id)
    items: dict[str, dict[str, int]] = {}
    paid: dict[str, int] = {}
    copies = 0
    with db.get_engine().connect() as conn:
        for row in conn.execute(statement).mappings():
            key = item_key(row["ItemKind"], row["ItemID"], row["VolumeNumber"])
            counts = items.setdefault(key, {OWNED: 0, WISHLIST: 0})
            counts[row["State"]] = counts.get(row["State"], 0) + 1
            if row["State"] == OWNED:
                copies += 1
                if row["PaidCents"] is not None:
                    currency = row["Currency"] or ""
                    paid[currency] = paid.get(currency, 0) + row["PaidCents"]
    on_shelf = sum(1 for counts in items.values() if counts.get(OWNED))
    wishlist = sum(1 for counts in items.values() if counts.get(WISHLIST) and not counts.get(OWNED))
    return {
        "comic_id": comic_id,
        "items": items,
        "totals": {"on_shelf": on_shelf, "copies": copies, "wishlist": wishlist, "paid_cents": paid},
    }


def summary() -> dict[str, Any]:
    """Totals across the whole shelf, for the Shelf tab's stat row."""
    totals: dict[str, Any] = {
        "copies": 0,
        "items": 0,
        "wishlist": 0,
        "graded": 0,
        "paid_cents": {},
        "estimate_cents": {},
        "estimated_copies": 0,
    }
    items: set[tuple[str, str, str | None, str | None]] = set()
    statement = select(
        physical_copies.c.ComicID,
        physical_copies.c.ItemKind,
        physical_copies.c.ItemID,
        physical_copies.c.VolumeNumber,
        physical_copies.c.State,
        physical_copies.c.GradeService,
        physical_copies.c.PaidCents,
        physical_copies.c.EstimateCents,
        physical_copies.c.Currency,
    )
    with db.get_engine().connect() as conn:
        for row in conn.execute(statement).mappings():
            if row["State"] == WISHLIST:
                totals["wishlist"] += 1
                continue
            totals["copies"] += 1
            items.add((row["ComicID"], row["ItemKind"], row["ItemID"], row["VolumeNumber"]))
            if row["GradeService"] and row["GradeService"] != "raw":
                totals["graded"] += 1
            currency = row["Currency"] or ""
            if row["PaidCents"] is not None:
                totals["paid_cents"][currency] = totals["paid_cents"].get(currency, 0) + row["PaidCents"]
            if row["EstimateCents"] is not None:
                totals["estimated_copies"] += 1
                totals["estimate_cents"][currency] = totals["estimate_cents"].get(currency, 0) + row["EstimateCents"]
    totals["items"] = len(items)
    return totals


def storage_places(limit: int = 50) -> list[str]:
    """Storage names in use, most recently used first, for the sheet's picker."""
    statement = (
        select(physical_copies.c.Storage, func.max(physical_copies.c.updated_at).label("last"))
        .where(physical_copies.c.Storage.is_not(None))
        .group_by(physical_copies.c.Storage)
        .order_by(func.max(physical_copies.c.updated_at).desc())
        .limit(max(1, min(int(limit), 200)))
    )
    with db.get_engine().connect() as conn:
        return [row[0] for row in conn.execute(statement)]


# --- writes ----------------------------------------------------------------------


def create_copy(body: Mapping[str, Any]) -> dict[str, Any]:
    """Add one copy. ``ComicID`` and ``ItemKind`` are required, plus ``ItemID``
    for an issue or annual, or ``VolumeNumber`` for a manga volume."""
    if not isinstance(body, Mapping):
        raise CopyError("invalid_body")
    values = _clean_fields(body, partial=False)
    now = _now()
    with db.get_engine().begin() as conn:
        target = _resolve_target(
            conn, body.get("ComicID"), body.get("ItemKind"), body.get("ItemID"), body.get("VolumeNumber")
        )
        default_format = target.pop("DefaultFormat")
        values.setdefault("Format", default_format)
        copy_id = uuid.uuid4().hex
        conn.execute(insert(physical_copies).values(CopyID=copy_id, created_at=now, updated_at=now, **target, **values))
    return get_copy(copy_id)


def update_copy(copy_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """Change the operator's fields on one copy. The item it points at is fixed."""
    if not isinstance(body, Mapping):
        raise CopyError("invalid_body")
    fixed = {"ComicID", "ItemKind", "ItemID", "VolumeNumber"} & set(body)
    if fixed:
        raise CopyError("field_not_editable", sorted(fixed)[0])
    values = _clean_fields(body, partial=True)
    with db.get_engine().begin() as conn:
        changed = conn.execute(
            update(physical_copies).where(physical_copies.c.CopyID == copy_id).values(updated_at=_now(), **values)
        ).rowcount
    if not changed:
        raise CopyError("copy_not_found", status=404)
    return get_copy(copy_id)


def delete_copy(copy_id: str) -> None:
    with db.get_engine().begin() as conn:
        removed = conn.execute(delete(physical_copies).where(physical_copies.c.CopyID == copy_id)).rowcount
    if not removed:
        raise CopyError("copy_not_found", status=404)


def mark_items(comic_id: Any, state: Any, items: Any) -> dict[str, Any]:
    """Bulk "Mark on shelf" / "Add to wishlist" from the series page.

    ``items`` is a list of ``{"ItemKind", "ItemID" | "VolumeNumber"}``. An item
    that already has an owned copy is left alone. Marking an item owned turns
    its wishlist entry into the owned copy instead of adding a second row; a
    wishlist mark adds an entry only where none exists.
    """
    if state not in STATES:
        raise CopyError("invalid_field", "State")
    if not isinstance(items, list) or not items or len(items) > 1000:
        raise CopyError("invalid_field", "items")
    created = promoted = skipped = 0
    now = _now()
    with db.get_engine().begin() as conn:
        for item in items:
            if not isinstance(item, Mapping):
                raise CopyError("invalid_field", "items")
            target = _resolve_target(conn, comic_id, item.get("ItemKind"), item.get("ItemID"), item.get("VolumeNumber"))
            default_format = target.pop("DefaultFormat")
            same_item = and_(
                physical_copies.c.ComicID == target["ComicID"],
                physical_copies.c.ItemKind == target["ItemKind"],
                physical_copies.c.ItemID == target["ItemID"]
                if target["ItemID"] is not None
                else physical_copies.c.VolumeNumber == target["VolumeNumber"],
            )
            existing = {
                row[0]: row[1]
                for row in conn.execute(
                    select(physical_copies.c.State, func.min(physical_copies.c.CopyID))
                    .where(same_item)
                    .group_by(physical_copies.c.State)
                )
            }
            if OWNED in existing or (state == WISHLIST and WISHLIST in existing):
                skipped += 1
                continue
            if state == OWNED and WISHLIST in existing:
                conn.execute(
                    update(physical_copies)
                    .where(physical_copies.c.CopyID == existing[WISHLIST])
                    .values(State=OWNED, updated_at=now)
                )
                promoted += 1
                continue
            conn.execute(
                insert(physical_copies).values(
                    CopyID=uuid.uuid4().hex,
                    State=state,
                    Format=default_format,
                    created_at=now,
                    updated_at=now,
                    **target,
                )
            )
            created += 1
    return {"created": created, "promoted": promoted, "skipped": skipped}
