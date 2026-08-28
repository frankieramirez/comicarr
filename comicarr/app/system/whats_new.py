#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Post-upgrade What's New: LAST_SEEN_VERSION detect, seed, dismiss, archive.

Install-wide state (decision #449). Detect is pure comparison; write only on
seed (key absent) or dismiss (Got it / Mark as read). Archive depth (#451):
floor at the pending range so modal overflow is never shorter than About;
when quiet, pad toward ~10 historical rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packaging.version import InvalidVersion, Version

import comicarr
from comicarr import logger

ARCHIVE_FLOOR = 10


@dataclass(frozen=True)
class DetectResult:
    """Outcome of pure last_seen vs current comparison (no I/O)."""

    kind: str
    pending: dict[str, str] | None = None


def _strip_v(text: str | None) -> str | None:
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None
    if text[:1] in ("v", "V"):
        text = text[1:]
    return text or None


def _parse(text: str | None) -> Version | None:
    stripped = _strip_v(text)
    if not stripped:
        return None
    try:
        return Version(stripped)
    except InvalidVersion:
        return None


def detect_pending(*, current: str | None, last_seen: str | None) -> DetectResult:
    """Pure compare of release versions. Never writes.

    | Condition | kind |
    |-----------|------|
    | last_seen absent/empty | seed |
    | current > last_seen | pending ``(last_seen, current]`` ends as {from, to} |
    | current == last_seen | quiet |
    | current < last_seen | quiet (do not write) |
    """
    current_s = _strip_v(current)
    last_s = _strip_v(last_seen)

    if not last_s:
        if current_s and _parse(current_s) is not None:
            return DetectResult(kind="seed")
        return DetectResult(kind="quiet")

    current_v = _parse(current_s)
    last_v = _parse(last_s)
    if current_v is None or last_v is None:
        return DetectResult(kind="quiet")

    if current_v > last_v:
        return DetectResult(
            kind="pending",
            pending={"from": last_s, "to": current_s},
        )
    return DetectResult(kind="quiet")


def _record_last_seen(version: str) -> None:
    """Persist LAST_SEEN_VERSION to config.ini under DATA_DIR."""
    try:
        comicarr.CONFIG.LAST_SEEN_VERSION = version
        ok = comicarr.CONFIG.writeconfig(values={"last_seen_version": version})
        if ok is False:
            raise RuntimeError("writeconfig returned False for last_seen_version")
    except Exception as e:
        logger.warn("[WHATS_NEW] Could not persist LAST_SEEN_VERSION=%s: %s" % (version, e))
        raise


def resolve_pending_whats_new(ctx) -> dict[str, str] | None:
    """Detect pending range; seed when key is absent. Returns pending or None.

    Seed writes ``LAST_SEEN_VERSION = current`` immediately and returns None
    (no notes on fresh install / first boot after this feature ships).
    Pending and quiet paths do not write.

    Seed failures are logged and treated as quiet so ``/api/system/version``
    still returns update state (same resilience idea as announce dedup).
    """
    from comicarr.app.system.service import get_release_version

    current = get_release_version()
    last_seen = getattr(comicarr.CONFIG, "LAST_SEEN_VERSION", None)
    result = detect_pending(current=current, last_seen=last_seen)

    if result.kind == "seed":
        version = _strip_v(current)
        if version:
            try:
                _record_last_seen(version)
            except Exception as e:
                logger.warn("[WHATS_NEW] Seed failed for %s: %s" % (version, e))
        return None

    return result.pending


def dismiss_whats_new(ctx) -> dict[str, Any]:
    """Operator acknowledgement — set LAST_SEEN_VERSION = current."""
    from comicarr.app.system.service import get_release_version

    current = _strip_v(get_release_version())
    if not current or _parse(current) is None:
        return {"success": False, "error": "current release version unavailable"}

    _record_last_seen(current)
    return {"success": True, "last_seen_version": current}


def archive_sections(
    sections: list[dict],
    *,
    current: str | None,
    last_seen: str | None,
    floor: int = ARCHIVE_FLOOR,
) -> list[dict]:
    """Slice changelog sections for Settings → About What's new.

    Newest-first, versions ``<= current``. Depth is ``max(pending_count, floor)``
    so the archive is never shorter than the modal's overflow target, and still
    reads as history when nothing is unread.
    """
    current_v = _parse(current)
    if current_v is None:
        return []

    last_v = _parse(last_seen)

    up_to: list[tuple[Version, dict]] = []
    for section in sections:
        ver = _parse(section.get("version"))
        if ver is None:
            continue
        if ver <= current_v:
            up_to.append((ver, section))

    up_to.sort(key=lambda item: item[0], reverse=True)

    pending_count = 0
    if last_v is not None:
        pending_count = sum(1 for ver, _ in up_to if ver > last_v)
    depth = max(pending_count, floor)
    return [section for _, section in up_to[:depth]]


def get_archive_notes(ctx) -> dict[str, Any]:
    """Structured About archive: floored/padded sections + pending range."""
    from comicarr.app.system.service import get_release_version
    from comicarr.changelog_notes import (
        get_cached_release_body,
        parse_changelog_text,
        parse_release_body,
        read_local_changelog,
    )

    current = _strip_v(get_release_version())
    last_seen = _strip_v(getattr(comicarr.CONFIG, "LAST_SEEN_VERSION", None))

    pending = resolve_pending_whats_new(ctx)
    last_seen = _strip_v(getattr(comicarr.CONFIG, "LAST_SEEN_VERSION", None))

    text = read_local_changelog(getattr(ctx, "prog_dir", None))
    sections = parse_changelog_text(text) if text else []

    cached = get_cached_release_body()
    if cached and current:
        cached_version = cached.get("version")
        known = {s["version"] for s in sections}
        if cached_version and cached_version not in known:
            remote = parse_release_body(cached.get("body"), version=cached_version)
            if remote and remote.get("bullets"):
                sections.append(remote)

    rows = archive_sections(
        sections,
        current=current,
        last_seen=last_seen,
        floor=ARCHIVE_FLOOR,
    )
    return {
        "sections": rows,
        "pending": pending,
        "current": current,
        "last_seen": last_seen,
    }
