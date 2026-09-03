#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Live-path wiring for manga sync, blended search, and bare-number settings."""

import ast
import datetime
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import comicarr.search as search
from comicarr.app.manga.acquisition import search_plan_for_series, search_terms_for_target
from comicarr.app.manga.ledger import volume_numbers_match
from comicarr.app.manga.parse import parse_in_series_context, parse_kwargs_for_series
from comicarr.app.manga.sync import arm_manga_sync_job, next_interval_run
from comicarr.rsscheck import mangaCheck
from comicarr.search import _build_manga_search_terms, manga_volume_search_terms
from comicarr.search_filer import manga_volume_satisfies

_INIT_PATH = Path(__file__).resolve().parents[2] / "comicarr" / "__init__.py"
_SEARCH_PATH = Path(__file__).resolve().parents[2] / "comicarr" / "search.py"
_FILECHECKER_PATH = Path(__file__).resolve().parents[2] / "comicarr" / "filechecker.py"


def _is_search_init(func):
    """Match both `search_init(...)` and `search.search_init(...)` call forms."""
    if isinstance(func, ast.Name):
        return func.id == "search_init"
    return isinstance(func, ast.Attribute) and func.attr == "search_init"


def _is_search_init_or_nzb(func):
    """Match a call to either search_init(...) or NZB_SEARCH(...)."""
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return name in {"search_init", "NZB_SEARCH"}


def _search_init_call_keywords(function_name, path):
    """Keyword names passed to every search_init() call inside `function_name`.

    search_init() is reached only through provider configuration and a global
    search lock, so the wiring is asserted from source instead -- the same
    approach test_init_arms_manga_sync_after_pause() takes.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        return [
            {kw.arg for kw in call.keywords}
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and _is_search_init(call.func)
        ]
    raise AssertionError("%s not found in %s" % (function_name, path.name))


def test_next_interval_run_fires_now_when_overdue():
    now = 1_700_000_000
    when = next_interval_run(now - 3600, 30, now_ts=now)
    assert when == datetime.datetime.utcfromtimestamp(now)


def test_next_interval_run_waits_out_the_remaining_interval():
    now = 1_700_000_000
    when = next_interval_run(now - 600, 30, now_ts=now)
    assert when == datetime.datetime.utcfromtimestamp(now + 1200)


def test_arm_manga_sync_job_modifies_next_run_unless_paused():
    scheduler = MagicMock()
    when = arm_manga_sync_job(scheduler, "Waiting", None, 60)
    scheduler.modify.assert_called_once_with(next_run_time=when)
    scheduler.reset_mock()
    assert arm_manga_sync_job(scheduler, "Paused", None, 60) is None
    scheduler.modify.assert_not_called()


def test_init_arms_manga_sync_after_pause():
    tree = ast.parse(_INIT_PATH.read_text(encoding="utf-8"))
    source = _INIT_PATH.read_text(encoding="utf-8")
    assert "MANGA_SYNC_SCHEDULER.pause()" in source
    assert "arm_manga_sync_job" in source
    helper_ids = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "_add_recurring_job":
            for keyword in node.keywords:
                if keyword.arg == "id" and isinstance(keyword.value, ast.Constant):
                    helper_ids.add(keyword.value.value)
    assert "manga_sync" in helper_ids


def test_blended_plan_skips_chapters_inside_released_volumes():
    series = {"MonitorMode": "blended"}
    issues = [
        {"IssueID": "md-x-ch1", "ChapterNumber": "1", "VolumeNumber": "1", "Status": "Wanted"},
        {"IssueID": "md-x-ch2", "ChapterNumber": "2", "VolumeNumber": "1", "Status": "Wanted"},
        {"IssueID": "md-x-ch100", "ChapterNumber": "100", "VolumeNumber": "2", "Status": "Wanted"},
        {"IssueID": "md-x-ch101", "ChapterNumber": "101", "VolumeNumber": None, "Status": "Wanted"},
    ]
    targets = search_plan_for_series(series, issues)
    kinds = {(item["kind"], str(item.get("number"))) for item in targets}
    assert ("volume", "1") in kinds
    assert ("volume", "2") in kinds
    assert ("chapter", "101") in kinds
    assert ("chapter", "1") not in kinds
    assert ("chapter", "2") not in kinds


def test_volumes_mode_does_not_search_wanted_chapters():
    series = {"MonitorMode": "volumes"}
    issues = [
        {"IssueID": "md-x-ch1", "ChapterNumber": "1", "VolumeNumber": "1", "Status": "Wanted"},
    ]
    targets = search_plan_for_series(series, issues)
    assert targets == [{"kind": "volume", "number": "1"}]


def test_owned_volume_drops_that_volume_from_the_plan():
    series = {"MonitorMode": "blended"}
    issues = [
        {"IssueID": "md-x-v1", "ChapterNumber": None, "VolumeNumber": "1", "Status": "Downloaded"},
        {"IssueID": "md-x-ch2", "ChapterNumber": "20", "VolumeNumber": "2", "Status": "Wanted"},
        {"IssueID": "md-x-ch21", "ChapterNumber": "21", "VolumeNumber": None, "Status": "Wanted"},
    ]
    targets = search_plan_for_series(series, issues)
    assert {"kind": "volume", "number": "1"} not in targets
    assert {"kind": "volume", "number": "2"} in targets
    assert any(item.get("id") == "md-x-ch21" for item in targets)


def test_manga_check_searches_blended_targets_not_every_wanted_chapter():
    series = {
        "ComicID": "md-abc",
        "ComicName": "One Piece",
        "ComicYear": "1999",
        "ComicPublisher": "Shueisha",
        "AlternateSearch": None,
        "UseFuzzy": None,
        "ComicVersion": None,
        "ComicName_Filesafe": "One Piece",
        "MonitorMode": "blended",
    }
    issues = [
        {"IssueID": "md-abc-ch1", "ChapterNumber": "1", "VolumeNumber": "1", "Status": "Wanted"},
        {"IssueID": "md-abc-ch100", "ChapterNumber": "100", "VolumeNumber": None, "Status": "Wanted"},
    ]
    with (
        patch("comicarr.CONFIG", MagicMock(FAILED_DOWNLOAD_HANDLING=False, FAILED_AUTO=False)),
        patch("comicarr.rsscheck.helpers") as mock_helpers,
        patch("comicarr.rsscheck.db") as mock_db,
        patch("comicarr.search.search_init") as mock_search,
    ):
        mock_db.select_all.side_effect = [[series], issues]
        mock_helpers.issue_status.return_value = False
        mangaCheck()

    assert mock_search.call_count == 2
    volume_call = mock_search.call_args_list[0]
    chapter_call = mock_search.call_args_list[1]
    assert volume_call.kwargs["volume_number"] == "1"
    assert volume_call.kwargs.get("chapter_number") in (None, "")
    assert chapter_call.kwargs["chapter_number"] == "100"
    assert chapter_call.kwargs.get("volume_number") in (None, "")
    assert volume_call.kwargs["booktype"] == "manga"


def test_build_manga_search_terms_is_exclusive_volume_or_chapter():
    volume_terms = _build_manga_search_terms("One Piece", None, "10")
    assert volume_terms == ["One Piece v10"]
    chapter_terms = _build_manga_search_terms("One Piece", "1161", "103")
    assert "One Piece c1161" in chapter_terms
    assert "One Piece chapter 1161" in chapter_terms
    assert not any("v103" in term for term in chapter_terms)


def test_parse_in_series_context_uses_persisted_volumes_mode():
    result = parse_in_series_context(
        "Naruto 12.cbr",
        series={"BareNumberMode": "volumes"},
        filenames=["Naruto 12.cbr", "Naruto 13.cbr"],
    )
    assert result["volume_number"] == 12
    assert result["chapter_number"] is None


def test_parse_kwargs_auto_passes_folder_bare_numbers():
    kwargs = parse_kwargs_for_series(
        {"BareNumberMode": "auto"},
        ["Naruto 1.cbr", "Naruto 2.cbr", "Naruto v10.cbz"],
        volume_count=72,
        chapter_count=700,
    )
    assert kwargs["bare_number_mode"] == "auto"
    assert kwargs["bare_numbers"] == ["1", "2"]
    assert kwargs["volume_count"] == 72


def test_searchforissue_passes_manga_numbers_to_search_init():
    """searchforissue() must supply the numbers manga search terms are built from.

    search_init() turns chapter_number/volume_number into "<series> v01" or
    "<series> c001" via _build_manga_search_terms(). Omit them and that helper
    receives (None, None) and returns [], so a manga Series is searched by
    issue number and volume-named releases are never queried -- silently, with
    no [SEARCH-MANGA] line to show for it.
    """
    calls = _search_init_call_keywords("searchforissue", _SEARCH_PATH)
    assert calls, "searchforissue() no longer calls search_init()"
    for keywords in calls:
        assert "content_type" in keywords
        assert "chapter_number" in keywords
        assert "volume_number" in keywords


def test_manga_volume_search_terms_maps_volume_targets_to_the_real_name():
    """Volume terms search bare AND match against the unsuffixed series name."""
    volume = manga_volume_search_terms("One-Punch Man", None, "1")
    assert volume == {"One-Punch Man v01": "One-Punch Man"}
    # The mapped value is what the matcher compares against: the release
    # "One-Punch Man v01 (2014) (Digital)" parses as "One-Punch Man", so
    # comparing against the query term would fail every result.
    assert volume["One-Punch Man v01"] == "One-Punch Man"

    # A chapter target must NOT be marked -- "<series> c001" is a real search
    # whose issue-number handling is unchanged.
    assert manga_volume_search_terms("One Piece", "1161", None) == {}
    # Neither number available: nothing to search bare.
    assert manga_volume_search_terms("One Piece", None, None) == {}


def test_manga_volume_satisfies_defers_to_the_ledger_comparison():
    """Acceptance asks the ledger; it does not carry its own volume rules.

    The spellings and edge cases are covered once, in test_manga_ledger.py.
    This only pins that acceptance uses that comparison -- a second copy here
    is exactly how the two would drift apart.
    """
    assert manga_volume_satisfies("v01", "1") is volume_numbers_match("v01", "1")
    assert manga_volume_satisfies("v02", "1") is volume_numbers_match("v02", "1")
    assert manga_volume_satisfies(None, "1") is False


def test_manga_volume_arm_precedes_the_comic_version_comparison():
    """The manga reading of "vNN" must win before the comic-version arms run.

    Those arms compare the release's vNN to the series' ComicVersion/year,
    which is the comic meaning (which RUN this is). For manga it is which BOOK,
    so a later volume is otherwise discarded as "Versions wrong" -- only volume
    1 of a v1 series would ever slip through.
    """
    filer_path = Path(__file__).resolve().parents[2] / "comicarr" / "search_filer.py"
    source = filer_path.read_text(encoding="utf-8")
    manga_arm = source.index("if manga_volume_pass and manga_volume_satisfies(")
    versions_wrong = source.index('logger.fdebug("Versions wrong. Ignoring possible match.")')
    assert manga_arm < versions_wrong
    # It must be the opening `if`, not an `elif` reached after a comic arm.
    assert "\n            if manga_volume_pass and manga_volume_satisfies(" in source


def test_match_entry_prefers_the_manga_match_name():
    """search_filer must compare against manga_match_name when it is set."""
    filer_path = Path(__file__).resolve().parents[2] / "comicarr" / "search_filer.py"
    source = filer_path.read_text(encoding="utf-8")
    assert 'is_info.get("manga_match_name")' in source
    # Both the parse and the match must use it, or the series comparison fails.
    assert source.count("watchcomic=match_name") == 2
    assert "watchcomic=ComicName" not in source


def test_nzb_search_accepts_and_receives_manga_volume_terms():
    """The bare-volume signal must reach NZB_SEARCH, or the suffix is appended.

    NZB_SEARCH builds "<series>%20<issue>" for anything with an IssueNumber. A
    manga volume target already carries its number in the name, so without this
    parameter the query becomes "<series> v01 001" and matches nothing.
    """
    tree = ast.parse(_SEARCH_PATH.read_text(encoding="utf-8"))
    signature = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "NZB_SEARCH")
    assert "manga_volume_terms" in {arg.arg for arg in signature.args.kwonlyargs + signature.args.args}

    handoff = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "search_the_matrix"
    )
    passed = {
        kw.arg
        for call in ast.walk(handoff)
        if isinstance(call, ast.Call) and _is_search_init_or_nzb(call.func)
        for kw in call.keywords
    }
    assert "manga_volume_terms" in passed


def test_manga_rss_path_passes_manga_numbers_to_search_init():
    """The RSS lane already honours the contract; it guards against regression."""
    rss_path = Path(__file__).resolve().parents[2] / "comicarr" / "rsscheck.py"
    calls = _search_init_call_keywords("mangaCheck", rss_path)
    assert calls, "mangaCheck() no longer calls search_init()"
    for keywords in calls:
        assert {"content_type", "chapter_number", "volume_number"} <= keywords


def test_gen_altnames_shreds_a_volume_term_carried_in_alternatesearch():
    """Characterises WHY volume terms cannot ride AlternateSearch.

    gen_altnames() splits that string on `!` and `#` (and reads `!!` as an
    alt-priority marker), so a series whose title contains one never survives
    the round trip. This is the reason manga_volume_altnames() builds the terms
    from the finished name list instead.
    """
    names = [x["ComicName"] for x in search.gen_altnames("Gantz!", "Gantz! v01", None, "want")]
    assert "Gantz! v01" not in names


def test_manga_volume_altnames_leaves_no_bare_name_to_search_by_issue_number():
    """Every pass for a volume target must be a volume query.

    NZB_SEARCH appends the issue number to any name that is not a volume term,
    and search_the_matrix stops on the first hit -- so leaving the bare series
    name in the list lets "One-Punch Man 030", a CHAPTER release, snatch the
    volume 30 row before the v30 pass ever runs.
    """
    altnames = [
        {"ComicName": "One-Punch Man", "unaltered_ComicName": "One-Punch Man"},
        {"ComicName": "Onepunchman", "unaltered_ComicName": "Onepunchman"},
    ]

    entries, terms = search.manga_volume_altnames(altnames, "30")

    assert [x["ComicName"] for x in entries] == ["One-Punch Man v30", "Onepunchman v30"]
    # the bare name is gone -- nothing left that would append an issue number
    assert "One-Punch Man" not in [x["ComicName"] for x in entries]
    # alternates keep their coverage rather than being dropped
    assert terms == {"One-Punch Man v30": "One-Punch Man", "Onepunchman v30": "Onepunchman"}


def test_manga_volume_altnames_keeps_a_bang_title_unsplit():
    """ "Gantz!" and "Working!!" must produce a usable volume term.

    The term is what NZB_SEARCH looks up to decide this is a volume pass, and
    what the matcher maps back to the real series name. A split term matches
    neither, so the lookup silently misses and the pass reverts to an
    issue-number search.
    """
    altnames = search.gen_altnames("Gantz!", None, None, "want")

    entries, terms = search.manga_volume_altnames(altnames, "1")

    assert [x["ComicName"] for x in entries] == ["Gantz! v01"]
    assert terms["Gantz! v01"] == "Gantz!"


def test_manga_volume_altnames_falls_back_when_no_term_can_be_built():
    """An unusable volume number must not leave the series unsearchable."""
    altnames = [{"ComicName": "Berserk", "unaltered_ComicName": "Berserk"}]

    entries, terms = search.manga_volume_altnames(altnames, None)

    assert entries == altnames
    assert terms == {}


def test_half_volume_keeps_its_fraction_through_search_and_match():
    """A v01.5 release must be searched for, parsed, and accepted.

    _pad_volume() used to truncate through int(), so a 1.5 volume searched
    "v01" and then failed the exact volume comparison (1 against 1.5) -- the
    row could never snatch.
    """
    assert search_terms_for_target("Kanojo", {"kind": "volume", "number": "1.5"}) == ["Kanojo v01.5"]
    # whole volumes keep their existing zero-padded form
    assert search_terms_for_target("Kanojo", {"kind": "volume", "number": "2"}) == ["Kanojo v02"]

    assert volume_numbers_match("v01.5", "1.5") is True
    # and the truncated form must NOT satisfy the half volume
    assert volume_numbers_match("v01", "1.5") is False


def test_filechecker_captures_a_fractional_manga_volume():
    """The volume pattern must keep the fraction, as the chapter pattern does."""
    pattern = re.compile(r"(?:v(?:ol(?:ume)?)?\.?\s*)(\d+(?:\.\d+)?)", re.IGNORECASE)
    source = _FILECHECKER_PATH.read_text(encoding="utf-8")
    assert pattern.pattern in source, "filechecker no longer uses the fractional volume pattern"

    assert pattern.search("Kanojo v01.5 (2020) (Digital)").group(1) == "01.5"
    assert pattern.search("Kanojo v01 (2020) (Digital)").group(1) == "01"
    # an extension must not be read as a fraction
    assert pattern.search("Kanojo v01.cbz").group(1) == "01"


def test_search_init_wires_volume_queries_instead_of_alternatesearch():
    """The wiring the two findings above depend on, asserted at the seam.

    search_init() is reached only through provider configuration and a global
    search lock, so this is asserted from source -- the same approach
    test_manga_volume_arm_precedes_the_comic_version_comparison() takes.
    """
    source = _SEARCH_PATH.read_text(encoding="utf-8")

    # both search loops (rss and api) rewrite the finished name list
    rewrite = "altnames, manga_volume_terms = manga_volume_altnames(altnames, volume_number)"
    assert source.count(rewrite) == 2, "a search loop still iterates un-rewritten altnames"

    # the AlternateSearch injection is reachable only for a NON-volume target
    guard = source.index("if not manga_volume_target:")
    injection = source.index('AlternateSearch = manga_alt_str + "##" + AlternateSearch')
    assert guard < injection, "volume terms are being injected into AlternateSearch again"


def test_a_multi_digit_fraction_survives_padding():
    """A volume/chapter fraction is carried as text, not through float rounding.

    `round(value % 1, 1)` keeps only ONE fractional digit, so 1.25 searched
    "v01.2" and 1.75 searched "v01.8" -- not truncations of the wanted volume
    but DIFFERENT ones, which the exact comparison then rejects, so the row
    could never snatch.
    """
    from comicarr.app.manga.acquisition import _pad_chapter, _pad_volume

    assert _pad_volume("1.25") == "01.25"
    assert _pad_volume("1.75") == "01.75"
    assert _pad_volume("1.05") == "01.05"
    assert _pad_chapter("1.25") == "001.25"
    assert _pad_chapter("1.75") == "001.75"

    # and the existing forms are unchanged
    assert _pad_volume("1.5") == "01.5"
    assert _pad_volume("2") == "02"
    assert _pad_chapter("165") == "165"


def test_a_fractional_volume_search_term_round_trips():
    """The term that is searched must satisfy the volume that was wanted."""
    from comicarr.app.manga.ledger import volume_numbers_match

    (term,) = search_terms_for_target("Kanojo", {"kind": "volume", "number": "1.25"})

    assert term == "Kanojo v01.25"
    assert volume_numbers_match("v01.25", "1.25") is True
    # the number the old rounding would have searched must NOT satisfy it
    assert volume_numbers_match("v01.2", "1.25") is False
