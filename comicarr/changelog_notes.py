#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Mechanical release-notes pipeline for in-app What's New surfaces.

Transforms local ``CHANGELOG.md`` (and, when the operator is behind, a
release body already cached from the update check) into structured sections
the UI can render without a Markdown dependency.

Rules (issue #472 / decision #450 + #451 amendments):

1. Strip leading hex prefixes: ``- e1601bf: `` → bullet text.
2. Drop bucket H3s (Patch/Minor/Major Changes, Bug Fixes, Features, …).
3. Flatten ``[text](url)`` → ``text``.
4. Strip trailing legacy ``(sha)`` suffixes.
5. Preserve multi-line bullet bodies as multi-line list items.
6. No invented dates; no editorial filter of contributor bullets.
"""

from __future__ import annotations

import os
import re
import threading

from packaging.version import InvalidVersion, Version

_CACHE_LOCK = threading.Lock()
_CACHED_RELEASE_BODY = None

_HEX_PREFIX = re.compile(r"^\s*[0-9a-f]{7,}:\s*", re.IGNORECASE)
_BUCKET_H3 = re.compile(
    r"^###\s+(Patch Changes|Minor Changes|Major Changes|Bug Fixes|Features|"
    r"Performance Improvements)\s*$",
    re.IGNORECASE,
)
_CHANGESETS_HEADING = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*$")
_LEGACY_HEADING = re.compile(r"^##\s+\[(\d+\.\d+\.\d+)\]\([^)]*\)(?:\s+\(([^)]+)\))?")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_LEGACY_COMMIT_TAIL = re.compile(r"\s*\(\s*[0-9a-f]{7,40}\s*\)\s*$", re.IGNORECASE)
_TOP_BULLET = re.compile(r"^-\s+")
_CONTINUATION = re.compile(r"^\s{2,}\S")


def set_cached_release_body(version, body):
    """Store release notes body from the update check (process memory only)."""
    global _CACHED_RELEASE_BODY
    stripped = _strip_leading_v(version)
    if not stripped:
        with _CACHE_LOCK:
            _CACHED_RELEASE_BODY = None
        return
    with _CACHE_LOCK:
        if body is None or str(body).strip() == "":
            _CACHED_RELEASE_BODY = None
        else:
            _CACHED_RELEASE_BODY = {"version": stripped, "body": str(body)}


def get_cached_release_body():
    """Return ``{"version", "body"}`` or None."""
    with _CACHE_LOCK:
        if _CACHED_RELEASE_BODY is None:
            return None
        return dict(_CACHED_RELEASE_BODY)


def clear_cached_release_body():
    """Test helper — reset the process cache."""
    global _CACHED_RELEASE_BODY
    with _CACHE_LOCK:
        _CACHED_RELEASE_BODY = None


def _strip_leading_v(text):
    if not text:
        return None
    text = str(text).strip()
    if text[:1] in ("v", "V"):
        return text[1:]
    return text


def _flatten_links(text):
    return _MARKDOWN_LINK.sub(r"\1", text)


def _strip_legacy_commit_tail(text):
    return _LEGACY_COMMIT_TAIL.sub("", text)


def _transform_bullet_line(text):
    """Apply mechanical rules 1, 3, 4 to a single line of bullet content."""
    text = _HEX_PREFIX.sub("", text)
    text = _flatten_links(text)
    text = _strip_legacy_commit_tail(text)
    return text


def _parse_version(value):
    try:
        return Version(str(value))
    except InvalidVersion:
        return None


def parse_changelog_text(text):
    """Parse full changelog markdown into structured sections.

    Returns a list of ``{"version": str, "bullets": [str, ...]}`` in file
    order (typically newest first already, but callers re-sort for ranges).
    """
    if not text:
        return []

    lines = text.split("\n")
    sections = []
    current = None
    bullet_buf = None

    def flush_bullet():
        nonlocal bullet_buf
        if current is None or bullet_buf is None:
            return
        joined = "\n".join(bullet_buf)
        joined = re.sub(r"\n{3,}", "\n\n", joined).rstrip()
        if joined.strip():
            current["bullets"].append(joined.strip())
        bullet_buf = None

    for line in lines:
        cs = _CHANGESETS_HEADING.match(line)
        legacy = _LEGACY_HEADING.match(line)

        if cs or legacy:
            flush_bullet()
            version = cs.group(1) if cs else legacy.group(1)
            current = {"version": version, "bullets": []}
            sections.append(current)
            continue

        if current is None:
            continue

        if _BUCKET_H3.match(line.strip()):
            flush_bullet()
            continue

        if _TOP_BULLET.match(line):
            flush_bullet()
            body = _TOP_BULLET.sub("", line)
            body = _transform_bullet_line(body)
            bullet_buf = [body]
            continue

        if bullet_buf is not None:
            if line.strip() == "" or _CONTINUATION.match(line):
                if line.strip() == "":
                    bullet_buf.append("")
                else:
                    bullet_buf.append(_transform_bullet_line(line.strip()))
                continue
            flush_bullet()

    flush_bullet()
    for section in sections:
        section["bullets"] = [b for b in (x.strip() for x in section["bullets"]) if b]
    return sections


def parse_release_body(body, version):
    """Parse a GitHub release body (changelog section, often without H2).

    Returns one section dict or None when there is nothing usable.
    """
    if body is None:
        return None
    text = str(body).strip()
    if not text:
        return None

    version = _strip_leading_v(version)
    if not version:
        return None

    has_heading = any(_CHANGESETS_HEADING.match(line) or _LEGACY_HEADING.match(line) for line in text.split("\n"))
    if has_heading:
        sections = parse_changelog_text(text)
        for section in sections:
            if section["version"] == version and section["bullets"]:
                return section
        return None

    wrapped = "## %s\n\n%s\n" % (version, text)
    sections = parse_changelog_text(wrapped)
    if not sections or not sections[0]["bullets"]:
        return None
    return {"version": version, "bullets": sections[0]["bullets"]}


def sections_in_range(sections, after, through):
    """Return sections in ``(after, through]``, newest-first."""
    after_v = _parse_version(after)
    through_v = _parse_version(through)
    if after_v is None or through_v is None:
        return []

    selected = []
    for section in sections:
        ver = _parse_version(section["version"])
        if ver is None:
            continue
        if ver > after_v and ver <= through_v:
            selected.append(section)

    selected.sort(key=lambda s: _parse_version(s["version"]) or Version("0"), reverse=True)
    return selected


def read_local_changelog(prog_dir):
    """Read ``CHANGELOG.md`` under prog_dir; return text or None."""
    if not prog_dir:
        return None
    path = os.path.join(prog_dir, "CHANGELOG.md")
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeError):
        return None


def get_release_notes(ctx, after, through):
    """Assemble structured release notes for a semver range.

    Primary source: local ``CHANGELOG.md`` under ``ctx.prog_dir``.
    Behind gap: if a requested version is not in the local file, the release
    body already cached from the update check (same transform) may fill it.
    Empty cache → omit those notes (UI falls back to the Release link later).
    """
    after = _strip_leading_v(after)
    through = _strip_leading_v(through)
    if not after or not through:
        return {"sections": []}

    text = read_local_changelog(getattr(ctx, "prog_dir", None))
    local_sections = parse_changelog_text(text) if text else []
    ranged = sections_in_range(local_sections, after=after, through=through)
    known = {s["version"] for s in ranged}

    cached = get_cached_release_body()
    if cached:
        cached_version = cached.get("version")
        if cached_version and cached_version not in known:
            ver = _parse_version(cached_version)
            after_v = _parse_version(after)
            through_v = _parse_version(through)
            if ver is not None and after_v is not None and through_v is not None and ver > after_v and ver <= through_v:
                remote_section = parse_release_body(cached.get("body"), version=cached_version)
                if remote_section and remote_section.get("bullets"):
                    ranged.append(remote_section)
                    ranged.sort(
                        key=lambda s: _parse_version(s["version"]) or Version("0"),
                        reverse=True,
                    )

    return {"sections": ranged}
