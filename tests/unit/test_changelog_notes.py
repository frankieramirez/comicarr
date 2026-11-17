#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Mechanical changelog notes transform (issue #472).

Seams under test:
- parse_changelog_text: both eras, six transform rules
- sections_in_range: (after, through] newest-first
- get_release_notes: local CHANGELOG + optional cached remote body
"""

from unittest.mock import MagicMock, patch

import pytest

from comicarr.app.core.context import AppContext
from comicarr.app.system import changelog_notes

# Real-ish fixture covering Changesets era, multi-line bullet, bucket H3s,
# and legacy semantic-release H2s with links + trailing (sha).
FIXTURE = """# Changelog

## 0.21.0

### Minor Changes

- fca4d33: Update checks now compare the Changesets release version against GitHub releases.

### Patch Changes

- 0d586ab: Default GIT_USER now points at the Comicarr project owner.
- 1876c6f: Fix Mylar3 config migration discarding every setting when the source config used NZBsu or DOGnzb

  `_BAD_DEFINITIONS` carried seven remapping entries for NZBsu and DOGnzb.

  The seven entries are removed.

## 0.20.12

### Patch Changes

- e1601bf: Show one release version across the sidebar, Settings, and About.

## [0.18.1](https://github.com/frankieramirez/comicarr/compare/v0.18.0...v0.18.1) (2026-06-09)

### Bug Fixes

- address open GitHub issues [#149](https://github.com/frankieramirez/comicarr/issues/149), [#150](https://github.com/frankieramirez/comicarr/issues/150) ([#161](https://github.com/frankieramirez/comicarr/issues/161)) ([b4bbc97](https://github.com/frankieramirez/comicarr/commit/b4bbc978e5907466ccef17572fb3609baea402ff))

## [0.18.0](https://github.com/frankieramirez/comicarr/compare/v0.17.1...v0.18.0) (2026-05-17)

### Features

- Restart-durable download/post-process pipeline ([#156](https://github.com/frankieramirez/comicarr/issues/156)) ([49b569f](https://github.com/frankieramirez/comicarr/commit/49b569fe37970862c61408836bc43dce2c0456fd))
"""


@pytest.fixture(autouse=True)
def _clear_release_body_cache():
    """Process-global cache must not leak across tests in this module."""
    changelog_notes.clear_cached_release_body()
    yield
    changelog_notes.clear_cached_release_body()


class TestParseChangelogText:
    def test_changesets_era_strips_hex_and_drops_bucket_h3s(self):
        sections = changelog_notes.parse_changelog_text(FIXTURE)
        by_version = {s["version"]: s for s in sections}

        assert "0.21.0" in by_version
        bullets = by_version["0.21.0"]["bullets"]
        assert bullets[0].startswith("Update checks now compare")
        assert not bullets[0].startswith("fca4d33")
        # Bucket headings must not appear as bullets.
        assert all("Patch Changes" not in b and "Minor Changes" not in b for b in bullets)
        assert any(b.startswith("Default GIT_USER") for b in bullets)

    def test_preserves_multiline_bullet_body(self):
        sections = changelog_notes.parse_changelog_text(FIXTURE)
        by_version = {s["version"]: s for s in sections}
        multi = next(b for b in by_version["0.21.0"]["bullets"] if "Mylar3 config migration" in b)
        assert "_BAD_DEFINITIONS_" in multi or "_BAD_DEFINITIONS" in multi
        assert "seven entries are removed" in multi
        assert "\n" in multi

    def test_legacy_era_flattens_links_and_strips_sha_tail(self):
        sections = changelog_notes.parse_changelog_text(FIXTURE)
        by_version = {s["version"]: s for s in sections}

        assert "0.18.1" in by_version
        bullet = by_version["0.18.1"]["bullets"][0]
        assert "https://" not in bullet
        assert "[#149]" not in bullet
        assert "#149" in bullet
        # Trailing (sha) stripped; issue refs like (#161) may remain as text
        # after link flatten, but commit sha tail must go.
        assert "b4bbc97" not in bullet
        assert "address open GitHub issues" in bullet

    def test_legacy_features_section(self):
        sections = changelog_notes.parse_changelog_text(FIXTURE)
        by_version = {s["version"]: s for s in sections}
        assert by_version["0.18.0"]["bullets"] == ["Restart-durable download/post-process pipeline (#156)"]

    def test_no_invented_dates_in_sections(self):
        sections = changelog_notes.parse_changelog_text(FIXTURE)
        for s in sections:
            assert "date" not in s or s.get("date") is None


class TestSectionsInRange:
    def test_open_closed_interval_newest_first(self):
        sections = changelog_notes.parse_changelog_text(FIXTURE)
        ranged = changelog_notes.sections_in_range(sections, after="0.18.0", through="0.21.0")
        versions = [s["version"] for s in ranged]
        assert versions == ["0.21.0", "0.20.12", "0.18.1"]

    def test_empty_when_nothing_in_range(self):
        sections = changelog_notes.parse_changelog_text(FIXTURE)
        assert changelog_notes.sections_in_range(sections, after="0.21.0", through="0.21.0") == []

    def test_includes_through_excludes_after(self):
        sections = changelog_notes.parse_changelog_text(FIXTURE)
        ranged = changelog_notes.sections_in_range(sections, after="0.20.12", through="0.21.0")
        assert [s["version"] for s in ranged] == ["0.21.0"]


class TestParseReleaseBody:
    """GitHub release body is a changelog section without the H2 (or with)."""

    def test_body_without_heading_uses_provided_version(self):
        body = """### Patch Changes

- abc1234: Remote-only release note about the new badge.
"""
        section = changelog_notes.parse_release_body(body, version="0.22.0")
        assert section is not None
        assert section["version"] == "0.22.0"
        assert section["bullets"] == ["Remote-only release note about the new badge."]

    def test_empty_body_returns_none(self):
        assert changelog_notes.parse_release_body("", version="0.22.0") is None
        assert changelog_notes.parse_release_body(None, version="0.22.0") is None

    def test_body_with_matching_h2_uses_that_section(self):
        body = """## 0.22.0

### Patch Changes

- abc1234: Note under matching heading.
"""
        section = changelog_notes.parse_release_body(body, version="0.22.0")
        assert section is not None
        assert section["version"] == "0.22.0"
        assert section["bullets"] == ["Note under matching heading."]

    def test_body_with_unrelated_h2_returns_none_when_versions_differ(self):
        body = """## 0.21.0

### Patch Changes

- abc1234: Wrong version section.
"""
        assert changelog_notes.parse_release_body(body, version="0.22.0") is None


class TestCheckGithubCachesReleaseBody:
    def test_behind_check_caches_body_for_notes(self, monkeypatch):
        from comicarr.app.system import versioncheck
        from comicarr.app.system import service as system_service

        changelog_notes.clear_cached_release_body()
        config = MagicMock(GIT_TOKEN=None, CHECK_GITHUB=True)
        monkeypatch.setattr("comicarr.CONFIG", config, raising=False)
        monkeypatch.setattr("comicarr.INSTALL_TYPE", "git", raising=False)
        monkeypatch.setattr("comicarr.CURRENT_VERSION", "aaaaaaa", raising=False)

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "tag_name": "v0.22.0",
            "body": "### Patch Changes\n\n- abc1234: Remote note from GitHub body.\n",
        }
        with (
            patch.object(versioncheck.requests, "get", return_value=response),
            patch.object(system_service, "get_release_version", return_value="0.21.0"),
            patch("comicarr.app.core.runtime.get_runtime_if_initialized", return_value=None),
        ):
            result = versioncheck.checkGithub()

        assert result["update_state"] == "behind"
        cached = changelog_notes.get_cached_release_body()
        assert cached is not None
        assert cached["version"] == "0.22.0"
        assert "Remote note from GitHub body" in cached["body"]
        changelog_notes.clear_cached_release_body()

    def test_current_check_clears_stale_cache(self, monkeypatch):
        from comicarr.app.system import versioncheck
        from comicarr.app.system import service as system_service

        changelog_notes.set_cached_release_body("0.22.0", "stale body")
        config = MagicMock(GIT_TOKEN=None, CHECK_GITHUB=True)
        monkeypatch.setattr("comicarr.CONFIG", config, raising=False)
        monkeypatch.setattr("comicarr.INSTALL_TYPE", "git", raising=False)
        monkeypatch.setattr("comicarr.CURRENT_VERSION", "aaaaaaa", raising=False)

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"tag_name": "v0.21.0", "body": "should clear"}
        with (
            patch.object(versioncheck.requests, "get", return_value=response),
            patch.object(system_service, "get_release_version", return_value="0.21.0"),
            patch("comicarr.app.core.runtime.get_runtime_if_initialized", return_value=None),
        ):
            versioncheck.checkGithub()

        assert changelog_notes.get_cached_release_body() is None


class TestGetReleaseNotes:
    def test_reads_local_changelog_from_prog_dir(self, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text(FIXTURE, encoding="utf-8")
        ctx = AppContext(prog_dir=str(tmp_path), data_dir=str(tmp_path / "data"), db_file=":memory:")
        result = changelog_notes.get_release_notes(ctx, after="0.20.12", through="0.21.0")
        assert [s["version"] for s in result["sections"]] == ["0.21.0"]
        assert result["sections"][0]["bullets"][0].startswith("Update checks")

    def test_missing_changelog_returns_empty_sections(self, tmp_path):
        ctx = AppContext(prog_dir=str(tmp_path), data_dir=str(tmp_path / "data"), db_file=":memory:")
        result = changelog_notes.get_release_notes(ctx, after="0.20.0", through="0.21.0")
        assert result == {"sections": []}

    def test_behind_gap_uses_cached_remote_body_not_local_only(self, tmp_path):
        # Local file has no 0.22.0 (operator is behind).
        (tmp_path / "CHANGELOG.md").write_text(FIXTURE, encoding="utf-8")
        ctx = AppContext(
            prog_dir=str(tmp_path),
            data_dir=str(tmp_path / "data"),
            db_file=":memory:",
            latest_version="0.22.0",
            update_state="behind",
        )
        with patch.object(
            changelog_notes,
            "get_cached_release_body",
            return_value={
                "version": "0.22.0",
                "body": "### Patch Changes\n\n- deadbee: Brand new remote release note.\n",
            },
        ):
            result = changelog_notes.get_release_notes(ctx, after="0.21.0", through="0.22.0")

        assert [s["version"] for s in result["sections"]] == ["0.22.0"]
        assert result["sections"][0]["bullets"] == ["Brand new remote release note."]

    def test_behind_gap_omits_notes_when_cache_empty(self, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text(FIXTURE, encoding="utf-8")
        ctx = AppContext(
            prog_dir=str(tmp_path),
            data_dir=str(tmp_path / "data"),
            db_file=":memory:",
            latest_version="0.22.0",
            update_state="behind",
        )
        with patch.object(changelog_notes, "get_cached_release_body", return_value=None):
            result = changelog_notes.get_release_notes(ctx, after="0.21.0", through="0.22.0")
        assert result == {"sections": []}

    def test_does_not_duplicate_version_already_in_local_file(self, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text(FIXTURE, encoding="utf-8")
        ctx = AppContext(prog_dir=str(tmp_path), data_dir=str(tmp_path / "data"), db_file=":memory:")
        with patch.object(
            changelog_notes,
            "get_cached_release_body",
            return_value={
                "version": "0.21.0",
                "body": "### Patch Changes\n\n- deadbee: Should not replace local notes.\n",
            },
        ):
            result = changelog_notes.get_release_notes(ctx, after="0.20.12", through="0.21.0")
        assert len(result["sections"]) == 1
        assert "Should not replace" not in result["sections"][0]["bullets"][0]
        assert result["sections"][0]["bullets"][0].startswith("Update checks")
