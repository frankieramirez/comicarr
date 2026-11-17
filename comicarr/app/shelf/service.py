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
copies. A copy points at an issue or annual by ``ItemID``, or at a manga volume
by ``VolumeNumber``. Each copy also keeps a snapshot of its series name, item
label and cover, because removing a series deletes its issue rows and the
operator still owns the books. Adding the series back re-links the copies,
since the ids are the provider's.

Nothing here changes an issue's status or what search looks for.
"""

from __future__ import annotations

import csv
import datetime
import io
import uuid
from typing import Any, Mapping

from sqlalchemy import delete, func, insert, or_, select, update

from comicarr import db
from comicarr.app.manga.ledger import normalize_volume_number
from comicarr.tables import annuals, comics, issues, physical_copies

# What an operator may record about a copy. Text fields map to their length limit.
_TEXT_LIMITS = {"VariantName": 200, "Grade": 32, "Storage": 200, "Notes": 4000}
_FIELDS = (*_TEXT_LIMITS, "PaidCents")
_TARGET = ("ComicID", "ItemID", "VolumeNumber")
_MAX_CENTS = 100_000_000_00
_MAX_MARK = 2000


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


def _clean_fields(body: Any, allowed: tuple[str, ...]) -> dict[str, Any]:
    """The operator's fields from ``body``, trimmed, with blanks stored as NULL."""
    if not isinstance(body, Mapping):
        raise CopyError("invalid_body")
    unknown = set(body) - set(allowed)
    if unknown:
        raise CopyError("unknown_field", sorted(unknown)[0])
    values: dict[str, Any] = {}
    for name in _FIELDS:
        if name not in body:
            continue
        value = body[name]
        if value is None or value == "":
            values[name] = None
        elif name == "PaidCents":
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_CENTS:
                raise CopyError("invalid_field", name)
            values[name] = value
        elif not isinstance(value, str):
            raise CopyError("invalid_field", name)
        elif len(value.strip()) > _TEXT_LIMITS[name]:
            raise CopyError("field_too_long", name)
        else:
            values[name] = value.strip() or None
    return values


# --- the item a copy points at -------------------------------------------------


def _series(conn, comic_id: Any) -> Mapping[str, Any]:
    if not isinstance(comic_id, str) or not comic_id.strip():
        raise CopyError("invalid_field", "ComicID")
    series = (
        conn.execute(
            select(comics.c.ComicID, comics.c.ComicName, comics.c.ComicImageURL, comics.c.ContentType).where(
                comics.c.ComicID == comic_id.strip()
            )
        )
        .mappings()
        .first()
    )
    if series is None:
        raise CopyError("series_not_found", status=404)
    return series


def _target(conn, series: Mapping[str, Any], item_id: Any, volume_number: Any) -> dict[str, Any]:
    """The stored identity and snapshot for a new copy, or CopyError."""
    target: dict[str, Any] = {
        "ComicID": series["ComicID"],
        "ItemID": None,
        "VolumeNumber": None,
        "SeriesName": series["ComicName"],
        "CoverURL": series["ComicImageURL"],
    }
    if volume_number not in (None, ""):
        if item_id not in (None, ""):
            raise CopyError("invalid_field", "VolumeNumber")
        if (series["ContentType"] or "").lower() != "manga":
            raise CopyError("volume_needs_manga", "VolumeNumber")
        number = normalize_volume_number(volume_number)
        if number is None or len(number) > 32:
            raise CopyError("invalid_field", "VolumeNumber")
        target["VolumeNumber"] = number
        target["ItemLabel"] = "Vol. %s" % number
        return target
    if not isinstance(item_id, str) or not item_id.strip():
        raise CopyError("invalid_field", "ItemID")
    item_id = item_id.strip()
    row = None
    for table, columns in (
        (issues, (issues.c.Issue_Number, issues.c.IssueName, issues.c.ImageURL)),
        (annuals, (annuals.c.Issue_Number, annuals.c.IssueName)),
    ):
        row = (
            conn.execute(select(*columns).where(table.c.IssueID == item_id, table.c.ComicID == series["ComicID"]))
            .mappings()
            .first()
        )
        if row is not None:
            break
    if row is None:
        raise CopyError("item_not_found", status=404)
    target["ItemID"] = item_id
    number = row["Issue_Number"]
    label = "#%s" % number if number not in (None, "") else ""
    target["ItemLabel"] = " · ".join(part for part in (label, row["IssueName"]) if part)
    if row.get("ImageURL"):
        target["CoverURL"] = row["ImageURL"]
    return target


# --- reads -----------------------------------------------------------------------

_JOINED = physical_copies.outerjoin(comics, comics.c.ComicID == physical_copies.c.ComicID)
_SELECT = select(physical_copies, comics.c.ComicName.label("_live_series_name")).select_from(_JOINED)


def _row(record: Mapping[str, Any]) -> dict[str, Any]:
    """A copy as the API returns it. A series still in the library supplies its current name."""
    item = dict(record)
    live_name = item.pop("_live_series_name")
    item["SeriesPresent"] = live_name is not None
    if live_name:
        item["SeriesName"] = live_name
    return item


def _get(copy_id: str) -> dict[str, Any]:
    with db.get_engine().connect() as conn:
        record = conn.execute(_SELECT.where(physical_copies.c.CopyID == copy_id)).mappings().first()
    if record is None:
        raise CopyError("copy_not_found", status=404)
    return _row(record)


def list_copies(
    *,
    comic_id: str | None = None,
    item_id: str | None = None,
    volume_number: str | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Copies matching every given filter, newest first, with their count and what was paid for them."""
    conditions = []
    if comic_id:
        conditions.append(physical_copies.c.ComicID == comic_id)
    if item_id:
        conditions.append(physical_copies.c.ItemID == item_id)
    if volume_number:
        conditions.append(physical_copies.c.VolumeNumber == normalize_volume_number(volume_number))
    if query and query.strip():
        pattern = "%%%s%%" % query.strip().lower()
        conditions.append(
            or_(
                *(
                    func.lower(column).like(pattern)
                    for column in (
                        physical_copies.c.SeriesName,
                        comics.c.ComicName,
                        physical_copies.c.ItemLabel,
                        physical_copies.c.VariantName,
                        physical_copies.c.Storage,
                        physical_copies.c.Notes,
                    )
                )
            )
        )
    totals = (
        select(func.count(), func.coalesce(func.sum(physical_copies.c.PaidCents), 0))
        .select_from(_JOINED)
        .where(*conditions)
    )
    page = (
        _SELECT.where(*conditions)
        .order_by(physical_copies.c.created_at.desc(), physical_copies.c.CopyID)
        .limit(limit)
        .offset(offset)
    )
    with db.get_engine().connect() as conn:
        total, paid = conn.execute(totals).one()
        rows = [_row(record) for record in conn.execute(page).mappings()]
    return {"results": rows, "total": total, "paid_cents": int(paid), "limit": limit, "offset": offset}


def series_shelf(comic_id: str) -> dict[str, dict[str, int]]:
    """How many copies each issue, annual and volume of one series has."""
    statement = (
        select(physical_copies.c.ItemID, physical_copies.c.VolumeNumber, func.count())
        .where(physical_copies.c.ComicID == comic_id)
        .group_by(physical_copies.c.ItemID, physical_copies.c.VolumeNumber)
    )
    shelf: dict[str, dict[str, int]] = {"issues": {}, "volumes": {}}
    with db.get_engine().connect() as conn:
        for item_id, volume_number, count in conn.execute(statement):
            if item_id is not None:
                shelf["issues"][item_id] = count
            else:
                shelf["volumes"][volume_number] = count
    return shelf


def export_csv() -> str:
    """Every copy as CSV, sorted the way a shelf is: by series, then item."""
    statement = _SELECT.order_by(
        func.lower(physical_copies.c.SeriesName), physical_copies.c.ItemLabel, physical_copies.c.created_at
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Series", "Item", "Variant", "Grade", "Paid", "Storage", "Notes", "Added"])
    with db.get_engine().connect() as conn:
        for record in conn.execute(statement).mappings():
            copy = _row(record)
            paid = copy["PaidCents"]
            cells = [
                copy["SeriesName"],
                copy["ItemLabel"],
                copy["VariantName"],
                copy["Grade"],
                "" if paid is None else "%d.%02d" % divmod(paid, 100),
                copy["Storage"],
                copy["Notes"],
                copy["created_at"][:10],
            ]
            # A leading = + - @ would run as a formula when a spreadsheet opens the file.
            writer.writerow(["'" + cell if cell and cell[0] in "=+-@" else cell or "" for cell in cells])
    return out.getvalue()


# --- writes ----------------------------------------------------------------------


def _insert(conn, target: Mapping[str, Any], values: Mapping[str, Any]) -> str:
    copy_id = uuid.uuid4().hex
    now = _now()
    conn.execute(insert(physical_copies).values(CopyID=copy_id, created_at=now, updated_at=now, **target, **values))
    return copy_id


def create_copy(body: Any) -> dict[str, Any]:
    """Add one copy. ``ComicID`` is required, plus ``ItemID`` for an issue or
    annual, or ``VolumeNumber`` for a manga volume."""
    values = _clean_fields(body, (*_TARGET, *_FIELDS))
    with db.get_engine().begin() as conn:
        target = _target(conn, _series(conn, body.get("ComicID")), body.get("ItemID"), body.get("VolumeNumber"))
        copy_id = _insert(conn, target, values)
    return _get(copy_id)


def update_copy(copy_id: str, body: Any) -> dict[str, Any]:
    """Change what is recorded about one copy. The item it points at is fixed."""
    values = _clean_fields(body, _FIELDS)
    with db.get_engine().begin() as conn:
        changed = conn.execute(
            update(physical_copies).where(physical_copies.c.CopyID == copy_id).values(updated_at=_now(), **values)
        ).rowcount
    if not changed:
        raise CopyError("copy_not_found", status=404)
    return _get(copy_id)


def delete_copy(copy_id: str) -> None:
    with db.get_engine().begin() as conn:
        removed = conn.execute(delete(physical_copies).where(physical_copies.c.CopyID == copy_id)).rowcount
    if not removed:
        raise CopyError("copy_not_found", status=404)


def mark_items(comic_id: Any, body: Any) -> dict[str, int]:
    """Bulk "Mark on shelf": add one plain copy to each listed item that has none.

    ``body`` carries ``ItemIDs`` and ``VolumeNumbers``. All or nothing: one
    unknown item refuses the whole request.
    """
    if not isinstance(body, Mapping):
        raise CopyError("invalid_body")
    item_ids = body.get("ItemIDs") or []
    volume_numbers = body.get("VolumeNumbers") or []
    if not isinstance(item_ids, list) or not isinstance(volume_numbers, list):
        raise CopyError("invalid_field", "ItemIDs")
    if not 0 < len(item_ids) + len(volume_numbers) <= _MAX_MARK:
        raise CopyError("invalid_field", "ItemIDs")
    created = 0
    with db.get_engine().begin() as conn:
        series = _series(conn, comic_id)
        targets = [_target(conn, series, item_id, None) for item_id in item_ids]
        targets += [_target(conn, series, None, number) for number in volume_numbers]
        have = set(
            conn.execute(
                select(physical_copies.c.ItemID, physical_copies.c.VolumeNumber).where(
                    physical_copies.c.ComicID == series["ComicID"]
                )
            ).tuples()
        )
        for target in targets:
            key = (target["ItemID"], target["VolumeNumber"])
            if key not in have:
                have.add(key)
                _insert(conn, target, {})
                created += 1
    return {"created": created, "skipped": len(targets) - created}
