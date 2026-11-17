#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Shelf tools: the print copies an operator owns or wants.

A copy never changes an issue's status or what Comicarr searches for, so
these writes start no acquisition and record no Activity.
"""

from typing import Annotated

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from comicarr.app.mcp.contracts import (
    ContractError,
    GradeService,
    Limit,
    Offset,
    SeriesId,
    ShelfCopy,
    ShelfCopyId,
    ShelfCopyPage,
    ShelfCopyState,
    ShelfFormat,
    ShelfItemKind,
    paging,
    tool_result,
)
from comicarr.app.shelf import service as shelf_service

_NOT_FOUND = {"series_not_found", "item_not_found", "copy_not_found"}
_MESSAGES = {
    "series_not_found": "No series has id %(series)s.",
    "item_not_found": "Series %(series)s has no issue or annual with that id.",
    "copy_not_found": "No shelf copy has id %(copy)s.",
    "volume_needs_manga": "Only a manga series has volumes; use item_kind issue or annual.",
}

# Optional fields an agent may set, mapped to the service's column names.
_FIELDS = {
    "state": "State",
    "format": "Format",
    "variant_name": "VariantName",
    "printing": "Printing",
    "grade_service": "GradeService",
    "grade": "Grade",
    "paid_cents": "PaidCents",
    "estimate_cents": "EstimateCents",
    "currency": "Currency",
    "bought_on": "BoughtOn",
    "bought_from": "BoughtFrom",
    "storage": "Storage",
    "barcode": "Barcode",
    "notes": "Notes",
}
_SNAKE = {column: name for name, column in _FIELDS.items()}


def _copy(row) -> ShelfCopy:
    return ShelfCopy(
        copy_id=row["CopyID"],
        series_id=row["ComicID"],
        series_name=row.get("SeriesName"),
        series_in_library=bool(row.get("SeriesPresent")),
        item_kind=row["ItemKind"],
        item_id=row.get("ItemID"),
        volume_number=row.get("VolumeNumber"),
        item_label=row.get("ItemLabel"),
        state=row["State"],
        format=row.get("Format"),
        variant_name=row.get("VariantName"),
        printing=row.get("Printing"),
        grade_service=row.get("GradeService"),
        grade=row.get("Grade"),
        paid_cents=row.get("PaidCents"),
        estimate_cents=row.get("EstimateCents"),
        currency=row.get("Currency"),
        bought_on=row.get("BoughtOn"),
        bought_from=row.get("BoughtFrom"),
        storage=row.get("Storage"),
        barcode=row.get("Barcode"),
        notes=row.get("Notes"),
    )


def _contract_error(error: shelf_service.CopyError, series=None, copy=None) -> ContractError:
    if error.code in _NOT_FOUND:
        return ContractError("not_found", _MESSAGES[error.code] % {"series": series, "copy": copy})
    if error.code in _MESSAGES:
        return ContractError("invalid_argument", _MESSAGES[error.code])
    field = _SNAKE.get(error.field or "", (error.field or "").lower())
    if error.code == "field_too_long":
        return ContractError("invalid_argument", "%s is too long." % field)
    return ContractError("invalid_argument", "%s is not valid." % (field or "The request"))


def _label(copy: ShelfCopy) -> str:
    return " ".join(part for part in (copy.series_name, copy.item_label) if part) or copy.copy_id


def register(server, get_ctx):
    """Add the shelf tools to ``server``. They need no AppContext."""

    @server.tool(
        name="list_shelf_copies",
        title="List shelf copies",
        description=(
            "List the print copies on the operator's shelf, owned or on the wishlist. "
            "Filter by series, state, item kind, storage place or text."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def list_shelf_copies(
        series_id: Annotated[str | None, Field(description="Only this series' copies.")] = None,
        state: Annotated[ShelfCopyState | None, Field(description="owned or wishlist.")] = None,
        item_kind: Annotated[ShelfItemKind | None, Field(description="issue, annual or volume.")] = None,
        storage: Annotated[str | None, Field(description="Exact storage place, such as a box name.")] = None,
        text: Annotated[
            str | None, Field(max_length=200, description="Part of the series name, label, variant or notes.")
        ] = None,
        limit: Limit = 25,
        offset: Offset = 0,
    ) -> Annotated[CallToolResult, ShelfCopyPage]:
        result = shelf_service.list_copies(
            comic_id=series_id,
            state=state,
            item_kind=item_kind,
            storage=storage,
            query=text,
            limit=limit,
            offset=offset,
        )
        copies = [_copy(row) for row in result["results"]]
        page = ShelfCopyPage(copies=copies, **paging(offset, len(copies), result["total"]))
        summary = "%d of %d shelf copies" % (len(copies), page.total)
        if page.next_offset is not None:
            summary += "; next page at offset %d" % page.next_offset
        return tool_result(page, summary + ".")

    @server.write_tool(
        name="add_shelf_copy",
        title="Add shelf copy",
        description=(
            "Record one print copy of an issue, an annual or a manga volume as owned or wishlisted. "
            "Each call adds a new copy, so two covers of one issue are two calls. "
            "It never changes the issue's status or what Comicarr searches for."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
        ),
    )
    def add_shelf_copy(
        series_id: SeriesId,
        item_kind: Annotated[ShelfItemKind, Field(description="issue, annual, or volume for a manga volume.")],
        item_id: Annotated[str | None, Field(description="The issue or annual id; leave out for a volume.")] = None,
        volume_number: Annotated[str | None, Field(description="The manga volume number, such as 12.")] = None,
        state: Annotated[ShelfCopyState, Field(description="owned or wishlist.")] = "owned",
        format: Annotated[ShelfFormat | None, Field(description="Defaults from the series type.")] = None,
        variant_name: Annotated[str | None, Field(description="Such as 1:25 virgin.")] = None,
        printing: Annotated[str | None, Field(description="Such as 1st printing.")] = None,
        grade_service: GradeService | None = None,
        grade: Annotated[str | None, Field(description="0.5 to 10, such as 9.4.")] = None,
        paid_cents: Annotated[int | None, Field(ge=0, description="Price paid, in cents.")] = None,
        estimate_cents: Annotated[int | None, Field(ge=0, description="The operator's own estimate, in cents.")] = None,
        currency: Annotated[str | None, Field(description="ISO 4217 code, such as USD.")] = None,
        bought_on: Annotated[str | None, Field(description="YYYY-MM-DD.")] = None,
        bought_from: str | None = None,
        storage: Annotated[str | None, Field(description="Where the copy is kept, such as a box name.")] = None,
        barcode: Annotated[str | None, Field(description="UPC, EAN or ISBN digits.")] = None,
        notes: str | None = None,
    ) -> Annotated[CallToolResult, ShelfCopy]:
        values = dict(locals())
        body = {"ComicID": series_id, "ItemKind": item_kind, "ItemID": item_id, "VolumeNumber": volume_number}
        body.update({column: values[name] for name, column in _FIELDS.items() if values[name] is not None})
        try:
            copy = _copy(shelf_service.create_copy(body))
        except shelf_service.CopyError as error:
            raise _contract_error(error, series=series_id) from None
        return tool_result(
            copy, "Added %s to the %s." % (_label(copy), "shelf" if copy.state == "owned" else "wishlist")
        )

    @server.write_tool(
        name="set_shelf_copy",
        title="Set shelf copy",
        description=(
            "Change fields on one shelf copy, such as moving it from the wishlist to owned, or setting its grade, "
            "price or storage. Fields left out stay as they are; an empty string clears a text field."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
    )
    def set_shelf_copy(
        copy_id: ShelfCopyId,
        state: ShelfCopyState | None = None,
        format: ShelfFormat | None = None,
        variant_name: str | None = None,
        printing: str | None = None,
        grade_service: GradeService | None = None,
        grade: str | None = None,
        paid_cents: Annotated[int | None, Field(ge=0)] = None,
        estimate_cents: Annotated[int | None, Field(ge=0)] = None,
        currency: str | None = None,
        bought_on: Annotated[str | None, Field(description="YYYY-MM-DD.")] = None,
        bought_from: str | None = None,
        storage: str | None = None,
        barcode: str | None = None,
        notes: str | None = None,
    ) -> Annotated[CallToolResult, ShelfCopy]:
        values = dict(locals())
        body = {column: values[name] for name, column in _FIELDS.items() if values[name] is not None}
        if not body:
            raise ContractError("invalid_argument", "Give at least one field to change.")
        try:
            copy = _copy(shelf_service.update_copy(copy_id, body))
        except shelf_service.CopyError as error:
            raise _contract_error(error, copy=copy_id) from None
        return tool_result(copy, "Updated %s." % _label(copy))
