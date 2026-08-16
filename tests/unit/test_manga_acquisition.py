#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Blended-frontier acquisition targets for manga."""

from comicarr.app.manga.acquisition import (
    blended_search_targets,
    booktype_bypasses_format_gates,
    search_terms_for_target,
)


def _volumes():
    return [{"VolumeNumber": n} for n in ("1", "2", "3")]


def _chapters():
    return [
        {"id": "md-x-ch1", "VolumeNumber": "1", "ChapterNumber": "1"},
        {"id": "md-x-ch100", "VolumeNumber": None, "ChapterNumber": "100"},
        {"id": "md-x-ch101", "VolumeNumber": "4", "ChapterNumber": "101"},
    ]


def test_blended_searches_missing_volumes_and_chapters_beyond():
    targets = blended_search_targets(
        _volumes(),
        _chapters(),
        owned_volumes=["1"],
        covered_chapter_ids=["md-x-ch1"],
        owned_chapter_ids=["md-x-ch101"],
        mode="blended",
    )
    kinds = [(item["kind"], item["number"]) for item in targets]
    assert ("volume", "2") in kinds
    assert ("volume", "3") in kinds
    assert ("chapter", "100") in kinds
    assert ("volume", "1") not in kinds
    assert ("chapter", "1") not in kinds
    assert ("chapter", "101") not in kinds


def test_volumes_only_and_chapters_only_toggles():
    volumes_only = blended_search_targets(_volumes(), _chapters(), owned_volumes=["1"], mode="volumes")
    assert all(item["kind"] == "volume" for item in volumes_only)
    chapters_only = blended_search_targets(
        _volumes(),
        _chapters(),
        owned_volumes=["1"],
        covered_chapter_ids=["md-x-ch1"],
        mode="chapters",
    )
    assert all(item["kind"] == "chapter" for item in chapters_only)
    assert [item["number"] for item in chapters_only] == ["100", "101"]


def test_volume_targets_search_v_prefix_not_chapter_tokens():
    terms = search_terms_for_target("One Piece", {"kind": "volume", "number": "10"})
    assert terms == ["One Piece v10"]
    chapter_terms = search_terms_for_target("One Piece", {"kind": "chapter", "number": "1161"})
    assert chapter_terms == ["One Piece c1161", "One Piece chapter 1161"]


def test_manga_booktype_bypasses_tpb_gates():
    assert booktype_bypasses_format_gates("manga") is True
    assert booktype_bypasses_format_gates("TPB") is False
