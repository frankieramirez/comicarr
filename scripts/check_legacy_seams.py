#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Comicarr is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Comicarr.  If not, see <http://www.gnu.org/licenses/>.

"""CI gate: ``comicarr/app/`` reaches legacy root modules only where ADR-0005 allows.

ADR-0005 sorts the root-level ``comicarr/*.py`` modules into three groups:

- **Infrastructure** (``INFRASTRUCTURE``): shared plumbing any code may import.
- **Foundations legacy** (``SEAMS``): each may be imported under
  ``comicarr/app/`` only by its seam module(s), named in section 2 of
  ``docs/architecture/foundations-plan.md``.
- **Deferred legacy**: every other root module. Today's imports from
  ``comicarr/app/`` are baselined; new ones fail.

Routers carry a stricter rule: a ``router.py`` imports no root module outside
Infrastructure, seam or not.

The scan is an AST walk, so function-local and relative imports count. It also
counts attribute access through the package (``comicarr.updater.forceRescan``
after a bare ``import comicarr``), which is how several services reach legacy
code without an import statement naming the module.

Existing crossings live in three allowlists keyed on
``(relative file path, root module)``. Each value is ``(reason, removal
trigger)``. All three are **shrink-only**: an entry that no longer matches a
crossing is itself an error, so removing a crossing deletes its waiver in the
same change.

Not governed: legacy modules importing each other, and legacy modules importing
``comicarr.app``. Those edges disappear as bodies move (ADR-0005).

Contributor-facing only — no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACKAGE = "comicarr"
PACKAGE_DIR = "comicarr"
SCAN_DIR = "comicarr/app"

SKIP_DIR_NAMES = {"__pycache__"}

INFRASTRUCTURE = frozenset({"logger", "db", "tables", "config", "encrypted", "helpers", "series_kind"})

# Foundations legacy module -> the seam modules allowed to import it under
# comicarr/app/. Most seams do not exist yet; each seam ticket creates its file.
SEAMS = {
    "notifiers": frozenset({"comicarr/app/notifications/service.py"}),
    "weeklypull": frozenset({"comicarr/app/weekly/pull.py"}),
    "weeklypullit": frozenset({"comicarr/app/weekly/pull.py"}),
    "rsscheck": frozenset({"comicarr/app/search/rss.py"}),
    "rsscheckit": frozenset({"comicarr/app/search/rss.py"}),
    "updater": frozenset(
        {
            "comicarr/app/series/rescan.py",
            "comicarr/app/downloads/snatch_record.py",
            "comicarr/app/series/refresh.py",
        }
    ),
    "importer": frozenset({"comicarr/app/series/add.py"}),
    "postprocessor": frozenset({"comicarr/app/downloads/postprocessing.py"}),
    "process": frozenset({"comicarr/app/downloads/postprocessing.py"}),
}

# --------------------------------------------------------------------------
# Foundations legacy crossings that do not go through the module's seam.
# Foundations closes only when this list is empty (ADR-0005).
# --------------------------------------------------------------------------
FOUNDATIONS_ALLOWLIST = {
    ("comicarr/app/downloads/service.py", "updater"): (
        "dupecheck calls dbUpdate and forceRescan; snatch bookkeeping calls nzblog and foundsearch",
        "#1205, #1206 and #1207 move these callers onto app/series/rescan.py, "
        "app/downloads/snatch_record.py and app/series/refresh.py",
    ),
    ("comicarr/app/imports/finalization.py", "importer"): (
        "manual import adds a missing series with addComictoDB",
        "#1209 moves Series add behind app/series/add.py",
    ),
    ("comicarr/app/imports/finalization.py", "updater"): (
        "rescans the series after files are placed (forceRescan)",
        "#1205 moves forceRescan callers onto app/series/rescan.py",
    ),
    ("comicarr/app/manga/sync.py", "importer"): (
        "adds manga series with addMangaToDB and addMangaToDB_MAL",
        "#1209 moves Series add behind app/series/add.py",
    ),
    ("comicarr/app/manga/sync.py", "rsscheck"): (
        "runs mangaCheck and mangadexNewChapterCheck",
        "#1204 puts RSS checking behind app/search/rss.py",
    ),
    ("comicarr/app/metadata/service.py", "updater"): (
        "rescans the series after a metadata change (forceRescan)",
        "#1205 moves forceRescan callers onto app/series/rescan.py",
    ),
    ("comicarr/app/search/service.py", "importer"): (
        "queues a series add on importer_thread",
        "#1209 moves Series add behind app/series/add.py",
    ),
    ("comicarr/app/search/service.py", "rsscheckit"): (
        "force RSS check runs rsscheckit.tehMain",
        "#1204 puts RSS checking behind app/search/rss.py",
    ),
    ("comicarr/app/series/location.py", "updater"): (
        "rescans the series after a folder move (forceRescan)",
        "#1205 moves forceRescan callers onto app/series/rescan.py",
    ),
    ("comicarr/app/series/service.py", "importer"): (
        "queues adds and refreshes on importer_thread and refresh_thread",
        "#1209 moves Series add behind app/series/add.py",
    ),
    ("comicarr/app/storyarcs/service.py", "importer"): (
        "Add missing series queues adds on importer_thread",
        "#1209 moves Series add behind app/series/add.py",
    ),
    ("comicarr/app/system/service.py", "notifiers"): (
        "notifier test buttons build each notifiers class",
        "#1202 moves notifications behind app/notifications/service.py and deletes notifiers.py",
    ),
    ("comicarr/app/weekly/service.py", "importer"): (
        "queues pull-list matches on issue_watcher_thread",
        "#1209 moves Series add behind app/series/add.py",
    ),
}

# --------------------------------------------------------------------------
# Routers importing a root module outside Infrastructure. Must reach zero
# before Foundations closes (ADR-0005).
# --------------------------------------------------------------------------
ROUTER_ALLOWLIST = {
    ("comicarr/app/opds/router.py", "getimage"): (
        "OPDS page streaming opens archives and scales pages directly",
        "#1201 moves the call into a new app/opds/service.py",
    ),
    ("comicarr/app/opds/router.py", "readinglist"): (
        "OPDS reading-list feed builds a Readinglist",
        "#1201 moves the call into a new app/opds/service.py",
    ),
    ("comicarr/app/series/router.py", "comicsync"): (
        "comic scan progress endpoint reads get_scan_progress",
        "#1201 moves the call into app/series/service.py",
    ),
    ("comicarr/app/series/router.py", "mangasync"): (
        "manga scan progress endpoint reads get_scan_progress",
        "#1201 moves the call into app/series/service.py",
    ),
}

# --------------------------------------------------------------------------
# Deferred legacy crossings. Baselined, shrink-only, not a Foundations gate.
# --------------------------------------------------------------------------
DEFERRED = "a change that moves this module's behavior under comicarr/app/; not a Foundations gate (ADR-0005)"

DEFERRED_ALLOWLIST = {
    ("comicarr/app/downloads/recovery.py", "failed"): ("recovery terminalizes failed downloads", DEFERRED),
    ("comicarr/app/downloads/recovery.py", "sabnzbd"): ("recovery queries SABnzbd for stranded jobs", DEFERRED),
    ("comicarr/app/downloads/recovery_classify.py", "nzbget"): ("classifies NZBGet history", DEFERRED),
    ("comicarr/app/downloads/recovery_classify.py", "sabnzbd"): ("classifies SABnzbd history", DEFERRED),
    ("comicarr/app/downloads/service.py", "failed"): ("terminalize_failed_download", DEFERRED),
    ("comicarr/app/downloads/service.py", "filechecker"): ("FileChecker for duplicate checks", DEFERRED),
    ("comicarr/app/downloads/service.py", "getcomics"): ("GetComics direct downloads (GC)", DEFERRED),
    ("comicarr/app/downloads/service.py", "nzbget"): ("NZBGet client", DEFERRED),
    ("comicarr/app/downloads/service.py", "sabnzbd"): ("SABnzbd client", DEFERRED),
    ("comicarr/app/downloads/service.py", "search"): ("FailedMark and searchforissue for retries", DEFERRED),
    ("comicarr/app/imports/candidates.py", "importinbox"): ("match_terms and score_series", DEFERRED),
    ("comicarr/app/imports/finalization.py", "cmtag"): ("tags placed files (cmtag.run)", DEFERRED),
    ("comicarr/app/imports/finalization.py", "filechecker"): ("validateAndCreateDirectory", DEFERRED),
    ("comicarr/app/imports/finalization.py", "scanutil"): ("COMIC_EXTENSIONS", DEFERRED),
    ("comicarr/app/imports/metadata.py", "filers"): ("FileHandlers for folder names", DEFERRED),
    ("comicarr/app/imports/metadata.py", "mangadex"): ("MangaDex lookups for import matching", DEFERRED),
    ("comicarr/app/imports/metadata.py", "metron"): ("get_cv_id and is_metron_id", DEFERRED),
    ("comicarr/app/imports/metadata.py", "myanimelist"): ("MyAnimeList get_manga_details", DEFERRED),
    ("comicarr/app/manga/parse.py", "manga_parser"): ("parse_manga_filename", DEFERRED),
    ("comicarr/app/manga/rescan.py", "scanutil"): ("COMIC_EXTENSIONS", DEFERRED),
    ("comicarr/app/metadata/service.py", "cmtag"): ("tags files (cmtag.run)", DEFERRED),
    ("comicarr/app/metadata/service.py", "cv"): ("ComicVine getComic", DEFERRED),
    ("comicarr/app/metadata/service.py", "filers"): ("FileHandlers for folder names", DEFERRED),
    ("comicarr/app/metadata/service.py", "getimage"): ("cover extract_image and retrieve_image", DEFERRED),
    ("comicarr/app/metadata/service.py", "mangadex"): ("MangaDex search_manga", DEFERRED),
    ("comicarr/app/metadata/service.py", "metron"): ("Metron get_series_image", DEFERRED),
    ("comicarr/app/search/evaluation.py", "filechecker"): ("FileChecker parses release names", DEFERRED),
    ("comicarr/app/search/exact_lookup.py", "mb"): ("haveit_for_comicvine and listLibrary", DEFERRED),
    ("comicarr/app/search/interactive.py", "search"): ("interactive search drives search.py", DEFERRED),
    ("comicarr/app/search/service.py", "filers"): ("FileHandlers for folder names", DEFERRED),
    ("comicarr/app/search/service.py", "mangadex"): ("MangaDex search_manga", DEFERRED),
    ("comicarr/app/search/service.py", "mb"): ("findComic", DEFERRED),
    ("comicarr/app/search/service.py", "metron"): ("Metron id helpers", DEFERRED),
    ("comicarr/app/search/service.py", "myanimelist"): ("MyAnimeList search_manga", DEFERRED),
    ("comicarr/app/search/service.py", "search"): ("searchforissue", DEFERRED),
    ("comicarr/app/series/location.py", "filers"): ("FileHandlers for folder names", DEFERRED),
    ("comicarr/app/series/service.py", "comicsync"): ("comicScan and import_selected_series", DEFERRED),
    ("comicarr/app/series/service.py", "filechecker"): ("validateAndCreateDirectory", DEFERRED),
    ("comicarr/app/series/service.py", "importinbox"): ("inboxScan", DEFERRED),
    ("comicarr/app/series/service.py", "mangasync"): ("mangaScan and import_selected_manga", DEFERRED),
    ("comicarr/app/storyarcs/service.py", "cv"): ("ComicVine getComic", DEFERRED),
    ("comicarr/app/storyarcs/service.py", "filechecker"): ("FileChecker and validateAndCreateDirectory", DEFERRED),
    ("comicarr/app/storyarcs/service.py", "filers"): ("FileHandlers for folder names", DEFERRED),
    ("comicarr/app/storyarcs/service.py", "mb"): ("findComic and storyarcinfo", DEFERRED),
    ("comicarr/app/storyarcs/service.py", "metron"): ("Metron id helpers", DEFERRED),
    ("comicarr/app/storyarcs/service.py", "readinglist"): ("Readinglist", DEFERRED),
    ("comicarr/app/system/service.py", "changelog_notes"): ("get_release_notes", DEFERRED),
    ("comicarr/app/system/service.py", "migration"): ("Mylar3Migration", DEFERRED),
    ("comicarr/app/system/service.py", "versioncheckit"): ("CheckVersion", DEFERRED),
    ("comicarr/app/system/whats_new.py", "changelog_notes"): ("changelog parsing helpers", DEFERRED),
    ("comicarr/app/weekly/cv_source.py", "cv"): ("ComicVine pulldetails", DEFERRED),
    ("comicarr/app/weekly/cv_source.py", "locg"): ("store_week", DEFERRED),
    ("comicarr/app/weekly/service.py", "locg"): ("League of Comic Geeks pull source", DEFERRED),
}

ALLOWLISTS = {
    "foundations": FOUNDATIONS_ALLOWLIST,
    "router": ROUTER_ALLOWLIST,
    "deferred": DEFERRED_ALLOWLIST,
}


class UnreadableSource(Exception):
    """A scanned file could not be read or parsed, so it was not checked."""


def _root_modules() -> frozenset[str]:
    """Every root-level ``comicarr/*.py`` module, read from disk so new ones count."""
    return frozenset(p.stem for p in (ROOT / PACKAGE_DIR).glob("*.py") if p.stem != "__init__")


def _iter_source_files():
    for path in sorted((ROOT / SCAN_DIR).rglob("*.py")):
        if not path.is_file() or SKIP_DIR_NAMES.intersection(path.relative_to(ROOT).parts):
            continue
        yield path


def _resolve_from(node: ast.ImportFrom, rel: str) -> str:
    """Absolute dotted module for an ``ImportFrom``, resolving relative levels."""
    module = node.module or ""
    if not node.level:
        return module
    base = rel[: -len(".py")].split("/")[:-1]
    parts = base[: len(base) - (node.level - 1)]
    if module:
        parts.append(module)
    return ".".join(parts)


def _root_module_of(dotted: str, root_modules: frozenset[str]) -> str | None:
    parts = dotted.split(".")
    if len(parts) >= 2 and parts[0] == PACKAGE and parts[1] in root_modules:
        return parts[1]
    return None


def _crossings(path: Path, rel: str, root_modules: frozenset[str]) -> list[tuple[int, str]]:
    """(lineno, root module) for every reference from ``rel`` to a root module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise UnreadableSource("%s: %s" % (rel, exc)) from exc

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            dotted = _resolve_from(node, rel)
            module = _root_module_of(dotted, root_modules)
            if module is not None:
                found.append((node.lineno, module))
            elif dotted == PACKAGE:
                # ``from comicarr import updater`` and ``from ... import updater``
                found.extend((node.lineno, a.name) for a in node.names if a.name in root_modules)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module = _root_module_of(alias.name, root_modules)
                if module is not None:
                    found.append((node.lineno, module))
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == PACKAGE
            and node.attr in root_modules
        ):
            # ``import comicarr`` then ``comicarr.updater.forceRescan(...)``
            found.append((node.lineno, node.attr))
    return found


def _classify(rel: str, module: str) -> str | None:
    """Allowlist a crossing belongs to, or None when the rule permits it."""
    if module in INFRASTRUCTURE:
        return None
    if rel.rsplit("/", 1)[-1] == "router.py":
        return "router"
    if module in SEAMS:
        return None if rel in SEAMS[module] else "foundations"
    return "deferred"


def main() -> int:
    root_modules = _root_modules()
    violations: list[tuple[str, int, str, str]] = []
    unreadable: list[str] = []
    matched: set[tuple[str, str, str]] = set()

    for path in _iter_source_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            crossings = _crossings(path, rel, root_modules)
        except UnreadableSource as exc:
            unreadable.append(str(exc))
            continue
        for lineno, module in crossings:
            kind = _classify(rel, module)
            if kind is None:
                continue
            if (rel, module) in ALLOWLISTS[kind]:
                matched.add((kind, rel, module))
            else:
                violations.append((rel, lineno, module, kind))

    stale = sorted(
        (kind, rel, module)
        for kind, entries in ALLOWLISTS.items()
        for rel, module in entries
        if (kind, rel, module) not in matched
    )

    if violations:
        print("New crossing from comicarr/app/ into a legacy root module (ADR-0005):", file=sys.stderr)
        for rel, lineno, module, kind in violations:
            if kind == "router":
                why = "routers import only Infrastructure root modules"
            elif kind == "foundations":
                why = "Foundations legacy; import it only through %s" % ", ".join(sorted(SEAMS[module]))
            else:
                why = "Deferred legacy; no new crossings"
            print("  %s:%d: comicarr.%s (%s)" % (rel, lineno, module, why), file=sys.stderr)
        print("", file=sys.stderr)
        print("Call the seam or a service instead. Seams are listed in section 2 of", file=sys.stderr)
        print("docs/architecture/foundations-plan.md. Do not add allowlist entries for", file=sys.stderr)
        print("new crossings: the lists in scripts/check_legacy_seams.py only shrink.", file=sys.stderr)

    if stale:
        if violations:
            print("", file=sys.stderr)
        print("Stale legacy seam allowlist entry, no such crossing in the tree:", file=sys.stderr)
        for kind, rel, module in stale:
            print("  %s_ALLOWLIST: %s -> comicarr.%s" % (kind.upper(), rel, module), file=sys.stderr)
        print("", file=sys.stderr)
        print("The crossing is gone, so delete the entry from scripts/check_legacy_seams.py.", file=sys.stderr)

    if unreadable:
        if violations or stale:
            print("", file=sys.stderr)
        print("Could not parse; the boundary was NOT checked in these files:", file=sys.stderr)
        for message in unreadable:
            print("  %s" % message, file=sys.stderr)

    if violations or stale or unreadable:
        return 1

    print(
        "Legacy seams OK: %d Foundations, %d router, %d deferred allowlisted crossing(s), no new ones"
        % (len(FOUNDATIONS_ALLOWLIST), len(ROUTER_ALLOWLIST), len(DEFERRED_ALLOWLIST))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
