#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Manga ledger contract — chapters, volumes, and the blended frontier."""

from comicarr.app.manga.ledger import (
    apply_volume_coverage,
    blended_progress,
    chapter_id,
    covers_to_volume_rows,
    last_released_volume,
    merge_refresh_row,
    normalize_volume_number,
    volume_id,
)

__all__ = [
    "apply_volume_coverage",
    "blended_progress",
    "chapter_id",
    "covers_to_volume_rows",
    "last_released_volume",
    "merge_refresh_row",
    "normalize_volume_number",
    "volume_id",
]
