#  Copyright (C) 2026 Comicarr contributors
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

"""CI gate: a landed Alembic revision file never changes.

Installs in the field sit at every landed revision, and the upgrade matrix
(``tests/integration/test_upgrade_matrix.py``) proves each one reaches head.
Editing a landed revision changes what "upgrade to revision N" means for a
database that already ran the old version, so every landed file in
``alembic/versions/`` is pinned by checksum in ``alembic/landed_checksums.json``.

A new revision fails until it is recorded::

    python3 scripts/check_migration_checksums.py --record

``--record`` only adds files that have no checksum yet. It never rewrites one.

Contributor-facing only, no changeset (CLAUDE.md).

Wire-in: ``npm run lint:guards``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = ROOT / "alembic" / "versions"
MANIFEST = ROOT / "alembic" / "landed_checksums.json"


def checksum(path: Path) -> str:
    """SHA-256 of the file with line endings normalized, so a CRLF checkout matches."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def revision_files(versions_dir: Path) -> dict[str, Path]:
    return {path.name: path for path in sorted(versions_dir.glob("*.py")) if path.name != "__init__.py"}


def load_manifest(manifest: Path) -> dict[str, str]:
    if not manifest.exists():
        return {}
    return json.loads(manifest.read_text(encoding="utf-8"))


def problems(versions_dir: Path = VERSIONS_DIR, manifest: Path = MANIFEST) -> list[str]:
    recorded = load_manifest(manifest)
    files = revision_files(versions_dir)
    found = []
    for name, digest in sorted(recorded.items()):
        if name not in files:
            found.append("%s: landed revision was deleted" % name)
        elif checksum(files[name]) != digest:
            found.append("%s: landed revision was edited; add a new revision instead" % name)
    for name in sorted(set(files) - set(recorded)):
        found.append("%s: no checksum recorded; run scripts/check_migration_checksums.py --record" % name)
    return found


def record(versions_dir: Path = VERSIONS_DIR, manifest: Path = MANIFEST) -> list[str]:
    recorded = load_manifest(manifest)
    added = []
    for name, path in revision_files(versions_dir).items():
        if name not in recorded:
            recorded[name] = checksum(path)
            added.append(name)
    manifest.write_text(json.dumps(dict(sorted(recorded.items())), indent=2) + "\n", encoding="utf-8")
    return added


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pin landed Alembic revision files by checksum.")
    parser.add_argument("--record", action="store_true", help="record checksums for new revision files")
    args = parser.parse_args(argv)

    if args.record:
        for name in record():
            print("recorded %s" % name)

    found = problems()
    if found:
        print("check_migration_checksums: %d problem(s)" % len(found))
        for line in found:
            print("  %s" % line)
        return 1
    print("check_migration_checksums: %d landed revision(s) unchanged" % len(load_manifest(MANIFEST)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
