#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""Pydantic input and output models for the MCP tools.

Every list result carries ``total`` and ``next_offset``; ``next_offset`` is
null on the last page.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Limit = Annotated[int, Field(ge=1, le=100, description="Page size, 1 to 100.")]
Offset = Annotated[int, Field(ge=0, description="Items to skip before this page.")]
SeriesKind = Literal["comic", "manga", "magazine"]


def next_offset(offset: int, returned: int, total: int) -> int | None:
    """The offset of the following page, or None when this page is the last."""
    following = offset + returned
    return following if following < total else None


class SeriesSummary(BaseModel):
    series_id: str
    name: str
    year: str | None
    publisher: str | None
    kind: SeriesKind
    status: str | None
    have: int = Field(description="Issues on disk.")
    total: int = Field(description="Issues the series has.")
    latest_issue: str | None


class SeriesPage(BaseModel):
    series: list[SeriesSummary]
    total: int = Field(description="Series matching the filters, across all pages.")
    next_offset: int | None
