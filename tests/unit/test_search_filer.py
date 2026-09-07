#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr import search_filer


def _config(**overrides):
    values = {
        "IGNORE_SEARCH_WORDS": [],
        "USE_MINSIZE": False,
        "MINSIZE": "10",
        "USE_MAXSIZE": False,
        "MAXSIZE": "1000",
        "IGNORE_COVERS": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _info(**overrides):
    values = {
        "ComicName": "Example Series",
        "nzbprov": "experimental",
        "RSS": "no",
        "UseFuzzy": "1",
        "StoreDate": "2024-01-01",
        "IssueDate": "2024-01-01",
        "digitaldate": "0000-00-00",
        "booktype": "Print",
        "ignore_booktype": False,
        "SeriesYear": "2024",
        "ComicVersion": None,
        "IssDateFix": "no",
        "ComicYear": "2024",
        "IssueID": "issue-1",
        "ComicID": "comic-1",
        "IssueNumber": "1",
        "manual": True,
        "newznab_host": None,
        "torznab_host": None,
        "oneoff": False,
        "tmpprov": "Experimental",
        "SARC": None,
        "IssueArcID": None,
        "cmloopit": 3,
        "findcomiciss": "1",
        "intIss": 1000,
        "chktpb": 0,
        "provider_stat": {"type": "experimental", "id": 1, "active": True, "hits": 0},
    }
    values.update(overrides)
    return values


def _entry(**overrides):
    values = {
        "title": "Example Series 001 (2024)",
        "link": "https://indexer.test/download?apikey=super-secret",
        "pubdate": "Wed, 10 Jan 2024 12:00:00 +0000",
        "length": "104857600",
        "site": "experimental",
        "id": "provider-item-1",
        "pack": False,
        "seeders": "7",
        "peers": "2",
    }
    values.update(overrides)
    return values


def _parsed(**overrides):
    values = {
        "parse_status": "success",
        "booktype": "issue",
        "series_volume": None,
        "issue_year": "2024",
        "issue_number": "1",
    }
    values.update(overrides)
    return values


def _matched(**overrides):
    values = {
        "process_status": "match",
        "justthedigits": "1",
        "booktype": "issue",
    }
    values.update(overrides)
    return values


@pytest.fixture(autouse=True)
def _matcher_environment(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _config())
    monkeypatch.setattr(comicarr, "COMICINFO", [])
    monkeypatch.setattr(search_filer.search, "generate_id", lambda _provider, identity, _name: str(identity))
    _install_parser(monkeypatch)


def _install_parser(monkeypatch, *, parsed=None, matched=None, match_error=None):
    parsed_result = parsed or _parsed()
    matched_result = matched or _matched()

    class FakeFileChecker:
        def __init__(self, *args, **kwargs):
            pass

        def listFiles(self):
            return parsed_result

        def matchIT(self, _parsed_result):
            if match_error is not None:
                raise match_error
            return matched_result

        def dynamic_replace(self, _series):
            return {"mod_seriesname": "Example Series"}

    monkeypatch.setattr(search_filer.filechecker, "FileChecker", FakeFileChecker)


def _reason(evaluation):
    return evaluation.verdict["reason_code"]


def test_accepted_candidate_is_normalized_and_credential_safe():
    evaluation = search_filer.search_check().evaluate_entry(_entry(), _info())

    assert evaluation.verdict == {
        "status": "accepted",
        "accepted": True,
        "overrideable": False,
        "reason_code": "accepted.issue",
        "reasons": [{"code": "accepted.issue", "message": "Accepted issue match"}],
        "match_kind": "standard",
    }
    assert evaluation.candidate == {
        "title": "Example Series 001 (2024)",
        "provider": "experimental",
        "source_kind": "unknown",
        "published_at": "Wed, 10 Jan 2024 12:00:00 +0000",
        "size_bytes": 104857600,
        "pack": False,
        "metrics": {"seeders": 7, "peers": 2},
    }
    assert evaluation.legacy_match["link"].endswith("super-secret")
    assert "super-secret" not in str(evaluation.as_dict())
    assert "link" not in evaluation.as_dict()["candidate"]
    assert "provider_stat" not in evaluation.as_dict()["candidate"]
    assert "reconstruction_hint" not in evaluation.as_dict()


def test_overrideable_rejection_retains_private_provider_identity_hint(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _config(IGNORE_SEARCH_WORDS=["repack"]))
    evaluation = search_filer.search_check().evaluate_entry(
        _entry(title="Example Series 001 REPACK"),
        _info(provider_stat={"type": "newznab", "id": 19, "api_key": "secret"}),
    )

    assert evaluation.verdict["overrideable"] is True
    assert evaluation.reconstruction_hint == {
        "provider_config_id": 19,
        "provider_type": "newznab",
        "provider_item_id": "provider-item-1",
    }
    assert "secret" not in str(evaluation.reconstruction_hint)
    assert "reconstruction_hint" not in evaluation.as_dict()


def test_candidate_override_revalidates_exactly_one_overrideable_reason(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _config(IGNORE_SEARCH_WORDS=["repack"]))
    checker = search_filer.search_check()
    entry = _entry(title="Example Series 001 REPACK")

    with search_filer.interactive_candidate_override("ignored.search_word"):
        evaluation = checker.evaluate_entry(entry, _info())

    assert evaluation.verdict["accepted"] is True
    assert evaluation.legacy_match["ComicTitle"] == "Example Series 001 REPACK"

    with pytest.raises(ValueError, match="not overrideable"):
        with search_filer.interactive_candidate_override("blocked.duplicate"):
            pass


def test_interactive_collection_disables_first_result_shortcut(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _config(IGNORE_SEARCH_WORDS=["repack"]))
    collected = []

    with search_filer.interactive_collection(
        on_evaluations=collected.extend,
        on_provider_complete=lambda _provider: None,
        on_provider_failure=lambda _provider, _code, _detail: None,
    ):
        match = search_filer.search_check().check_for_first_result(
            [_entry(), _entry(title="Example Series 001 REPACK", id="provider-item-2")],
            _info(),
        )

    assert match["ComicTitle"] == "Example Series 001 (2024)"
    assert [evaluation.verdict["reason_code"] for evaluation in collected] == [
        "accepted.issue",
        "ignored.search_word",
    ]


def test_provider_display_cannot_expose_a_credential_bearing_endpoint():
    secret = "provider-config-secret"
    info = _info(
        nzbprov="dognzb",
        newznab_host=(f"https://user:{secret}@indexer.test?apikey={secret}", "endpoint", "1", secret),
        provider_stat={"type": "newznab", "api_key": secret},
    )

    evaluation = search_filer.search_check().evaluate_entry(_entry(), info)
    public = evaluation.as_dict()

    assert public["candidate"]["provider"] == "Usenet provider"
    assert secret not in str(public)


@pytest.mark.parametrize(
    ("config", "entry", "info", "reason_code", "overrideable"),
    [
        (
            _config(IGNORE_SEARCH_WORDS=["repack"]),
            _entry(title="Example Series 001 REPACK"),
            _info(),
            "ignored.search_word",
            True,
        ),
        (_config(USE_MINSIZE=True, MINSIZE="200"), _entry(), _info(), "rejected.size_below_min", True),
        (_config(USE_MAXSIZE=True, MAXSIZE="50"), _entry(), _info(), "rejected.size_above_max", True),
        (
            _config(IGNORE_COVERS=True),
            _entry(title="Example Series 001 Covers Only"),
            _info(),
            "rejected.cover_only",
            True,
        ),
        (
            _config(),
            {key: value for key, value in _entry().items() if key != "pubdate"},
            _info(nzbprov="dognzb", provider_stat={"type": "newznab"}),
            "invalid.pubdate_missing",
            False,
        ),
        (
            _config(),
            _entry(),
            _info(UseFuzzy="0", StoreDate="0000-00-00", IssueDate="0000-00-00"),
            "invalid.reference_date_missing",
            False,
        ),
        (
            _config(),
            _entry(pubdate="not-a-date"),
            _info(UseFuzzy="0"),
            "invalid.pubdate_unparseable",
            False,
        ),
        (
            _config(),
            _entry(pubdate="Wed, 10 Jan 2024 12:00:00 +0000"),
            _info(
                UseFuzzy="0",
                StoreDate="2024-02-01",
                IssueDate="2024-02-01",
                digitaldate="2024-02-01",
            ),
            "rejected.before_reference_date",
            True,
        ),
    ],
)
def test_early_rejection_reasons_are_stable(monkeypatch, config, entry, info, reason_code, overrideable):
    monkeypatch.setattr(comicarr, "CONFIG", config)

    evaluation = search_filer.search_check().evaluate_entry(entry, info)

    assert _reason(evaluation) == reason_code
    assert evaluation.verdict["accepted"] is False
    assert evaluation.verdict["overrideable"] is overrideable
    assert evaluation.legacy_match is None


def test_datetime_rejection_does_not_fall_through_to_disagreeing_integer_comparison(monkeypatch):
    integer_times = iter([300, 1706659200, 100, 1706659200, 100])
    monkeypatch.setattr(search_filer.time, "mktime", lambda _value: next(integer_times))

    evaluation = search_filer.search_check().evaluate_entry(
        _entry(pubdate="Wed, 10 Jan 2024 12:00:00 +0000"),
        _info(
            UseFuzzy="0",
            StoreDate="2024-02-01",
            IssueDate="2024-02-01",
            digitaldate="2024-02-01",
        ),
    )

    assert _reason(evaluation) == "rejected.before_reference_date"


class TestStoreDateGateOnAMangaVolumePass:
    """A volume number identifies the book; a street date cannot improve on it.

    The store-date comparison is a periodical tiebreak: an issue NUMBER recycles
    across runs, so the street date says which run a result belongs to. A volume
    number does not recycle, and digital manga is routinely posted before the
    street date ComicVine records -- so on a volume pass the gate only discards
    correct files.
    """

    _EARLY = dict(
        UseFuzzy="0",
        StoreDate="2024-02-01",
        IssueDate="2024-02-01",
        digitaldate="2024-02-01",
    )

    @staticmethod
    def _evaluate(**info):
        return search_filer.search_check().evaluate_entry(
            _entry(pubdate="Wed, 10 Jan 2024 12:00:00 +0000"),
            _info(**info),
        )

    def test_a_volume_pass_survives_a_pubdate_before_the_store_date(self):
        """The real rejection: OPM v06 posted 2016-04-13, store date 2016-04-27."""
        evaluation = self._evaluate(manga_match_name="Example Series", **self._EARLY)
        assert _reason(evaluation) != "rejected.before_reference_date"

    def test_a_periodical_with_the_same_dates_is_STILL_rejected(self):
        """Control: this must stay a rejection, or the gate is disabled, not scoped."""
        evaluation = self._evaluate(**self._EARLY)
        assert _reason(evaluation) == "rejected.before_reference_date"

    def test_the_exemption_needs_the_volume_pass_not_merely_a_manga_series(self):
        """manga_match_name is set only by the volume pass; a chapter pass keeps
        normal issue-number handling and so keeps the date tiebreak."""
        evaluation = self._evaluate(manga_match_name=None, booktype="Manga", **self._EARLY)
        assert _reason(evaluation) == "rejected.before_reference_date"


@pytest.mark.parametrize(
    ("parsed", "matched", "match_error", "info", "reason_code"),
    [
        (_parsed(), _matched(), RuntimeError("parser broke"), _info(), "error.matcher_exception"),
        (_parsed(), _matched(process_status="fail"), None, _info(), "rejected.series_mismatch"),
        (_parsed(booktype="TPB"), _matched(), None, _info(), "rejected.book_type"),
        (_parsed(parse_status="fail"), _matched(), None, _info(booktype="issue"), "rejected.unparseable_title"),
        (_parsed(issue_year="2023"), _matched(), None, _info(UseFuzzy="0"), "rejected.year_mismatch"),
        (
            _parsed(series_volume="v2"),
            _matched(),
            None,
            _info(ComicVersion="v1"),
            "rejected.volume_mismatch",
        ),
        (_parsed(), _matched(justthedigits="2"), None, _info(), "rejected.issue_mismatch"),
    ],
)
def test_matcher_rejection_reasons_are_stable(
    monkeypatch,
    parsed,
    matched,
    match_error,
    info,
    reason_code,
):
    _install_parser(monkeypatch, parsed=parsed, matched=matched, match_error=match_error)

    evaluation = search_filer.search_check().evaluate_entry(_entry(), info)

    assert _reason(evaluation) == reason_code
    assert evaluation.verdict["status"] == ("error" if reason_code.startswith("error.") else "rejected")


def test_manga_booktype_does_not_trip_tpb_format_gate(monkeypatch):
    _install_parser(monkeypatch, parsed=_parsed(booktype="issue"), matched=_matched())

    evaluation = search_filer.search_check().evaluate_entry(_entry(), _info(booktype="manga"))

    assert _reason(evaluation) != "rejected.book_type"


def _pack_entry(**overrides):
    values = _entry(
        title="Example Series 001-010 (2024)",
        site="DDL(GetComics)",
        filename="Example Series 001-010 (2024)",
        series="Example Series",
        gc_booktype="issue",
        issues=["1", "2", "3"],
        year="2024",
        pack=True,
        size="100M",
        link="https://getcomics.info/post/123",
    )
    values.update(overrides)
    return values


def test_pack_candidate_and_pack_failure_reasons(monkeypatch):
    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", lambda *_args, **_kwargs: {"valid": True, "issues": []})
    info = _info(nzbprov="DDL(GetComics)", tmpprov="DDL(GetComics)")

    accepted = search_filer.search_check().evaluate_entry(_pack_entry(), info)
    assert _reason(accepted) == "accepted.pack"
    assert accepted.verdict["match_kind"] == "pack"
    assert accepted.candidate["source_kind"] == "ddl"

    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", lambda *_args, **_kwargs: {"valid": False})
    absent = search_filer.search_check().evaluate_entry(_pack_entry(), info)
    assert _reason(absent) == "rejected.pack_issue_absent"

    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", MagicMock(side_effect=RuntimeError("lookup failed")))
    failed = search_filer.search_check().evaluate_entry(_pack_entry(), info)
    assert _reason(failed) == "error.pack_lookup_exception"


def test_non_ddl_volume_pack_is_detected_and_accepted(monkeypatch):
    calls = {}

    def fake_issue_find_ids(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"valid": True, "issues": [{"issueid": "id-1"}]}

    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", fake_issue_find_ids)
    info = _info(
        nzbprov="torznab",
        tmpprov="nyaa [api]",
        booktype="manga",
        allow_packs=True,
        RSS="yes",
        torznab_host=("nyaa", "https://nyaa.test", "0", "key"),
    )
    entry = _entry(title="Example Series v01-14 (2021-2025) (Digital)", site="torznab")

    evaluation = search_filer.search_check().evaluate_entry(entry, info)

    assert _reason(evaluation) == "accepted.pack"
    assert evaluation.verdict["match_kind"] == "pack"
    assert evaluation.legacy_match["pack"] is True
    assert evaluation.legacy_match["pack_numbers"] == "1-14"
    assert evaluation.legacy_match["kind"] == "torrent"
    # the entry is enriched so the downstream pack snatch/notify path works
    assert entry["pack"] is True
    assert entry["issues"] == "1-14"
    assert entry["series"] == "Example Series"
    assert calls["args"][2] == "1-14"
    assert calls["kwargs"] == {"kind": "volume", "span_end": None}


def test_non_ddl_numberless_series_pack_is_detected_and_accepted(monkeypatch):
    # "Solo Leveling (2021-2026) (Digital)" carries no issue range at all;
    # the complete-series detector claims it when packs are allowed (#744).
    calls = {}

    def fake_issue_find_ids(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"valid": True, "issues": [{"issueid": "id-1"}]}

    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", fake_issue_find_ids)
    info = _info(
        nzbprov="torznab",
        tmpprov="nyaa [api]",
        booktype="manga",
        allow_packs=True,
        RSS="yes",
        torznab_host=("nyaa", "https://nyaa.test", "0", "key"),
    )
    entry = _entry(title="Example Series (2021-2026) (Digital) (1r0n)", site="torznab")

    evaluation = search_filer.search_check().evaluate_entry(entry, info)

    assert _reason(evaluation) == "accepted.pack"
    assert evaluation.verdict["match_kind"] == "pack"
    assert evaluation.legacy_match["pack"] is True
    assert evaluation.legacy_match["pack_numbers"] == "all"
    assert entry["pack"] is True
    assert entry["issues"] == "all"
    assert entry["series"] == "Example Series"
    assert calls["args"][2] == "all"
    assert calls["kwargs"] == {"kind": "series", "span_end": "2026"}


def test_numberless_series_pack_without_allow_packs_is_not_detected():
    entry = _entry(title="Example Series (2021-2026) (Digital)")

    evaluation = search_filer.search_check().evaluate_entry(entry, _info(booktype="manga"))

    assert evaluation.legacy_match["pack"] is False


def test_numberless_series_pack_is_not_detected_for_print_series(monkeypatch):
    # On a print comic "(2021-2026)" states when the series ran, not what the
    # release holds. Claiming it would sweep every open issue row into the
    # pack and mark it Snatched, so the detector stays manga-only.
    def fail_issue_find_ids(*_args, **_kwargs):
        raise AssertionError("a print series must never claim a numberless series pack")

    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", fail_issue_find_ids)
    info = _info(
        nzbprov="torznab",
        tmpprov="nyaa [api]",
        booktype="Print",
        allow_packs=True,
        RSS="yes",
        torznab_host=("nyaa", "https://nyaa.test", "0", "key"),
    )
    entry = _entry(title="Example Series (2021-2026) (Digital) (1r0n)", site="torznab")

    evaluation = search_filer.search_check().evaluate_entry(entry, info)

    assert evaluation.legacy_match["pack"] is False
    assert entry["pack"] is False


def test_non_ddl_issue_range_pack_is_accepted_for_print_series(monkeypatch):
    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", lambda *_args, **_kwargs: {"valid": True, "issues": []})
    info = _info(allow_packs=True)
    entry = _entry(title="Example Series #1-10 (2024)")

    evaluation = search_filer.search_check().evaluate_entry(entry, info)

    assert _reason(evaluation) == "accepted.pack"


def test_pack_title_without_allow_packs_uses_single_issue_path():
    entry = _entry(title="Example Series v01-14 (2021-2025) (Digital)")

    evaluation = search_filer.search_check().evaluate_entry(entry, _info(booktype="manga"))

    # the stub parser matches, proving the legacy single-issue path ran
    assert _reason(evaluation) == "accepted.issue"
    assert evaluation.legacy_match["pack"] is False


def test_volume_pack_is_not_matched_against_issue_tracked_series():
    # A v01-14 release cannot satisfy individual issues 1-14 of a Print
    # series, so detection must not trigger for issue-tracked booktypes.
    entry = _entry(title="Example Series v01-14 (2021-2025) (Digital)")

    evaluation = search_filer.search_check().evaluate_entry(entry, _info(allow_packs=True, booktype="Print"))

    assert evaluation.legacy_match["pack"] is False


def test_non_ddl_pack_missing_wanted_issue_is_rejected(monkeypatch):
    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", lambda *_args, **_kwargs: {"valid": False})
    info = _info(allow_packs=True)
    entry = _entry(title="Example Series #1-10 (2024)")

    evaluation = search_filer.search_check().evaluate_entry(entry, info)

    assert _reason(evaluation) == "rejected.pack_issue_absent"


def test_rss_getcomics_pack_uses_post_id_as_nzbid(monkeypatch):
    monkeypatch.setattr(search_filer.helpers, "issue_find_ids", lambda *_args, **_kwargs: {"valid": True, "issues": []})
    info = _info(nzbprov="DDL(GetComics)", tmpprov="DDL(GetComics)", RSS="yes")

    evaluation = search_filer.search_check().evaluate_entry(_pack_entry(link=123), info)

    assert evaluation.legacy_match["nzbid"] == 123
    assert evaluation.legacy_match["link"] == "https://getcomics.info/?p=123"


def test_alternate_match_is_explainable_and_remains_filtered(monkeypatch):
    _install_parser(monkeypatch, matched=_matched(process_status="alt_match"))
    evaluation = search_filer.search_check().evaluate_entry(_entry(), _info(manual=False))

    assert _reason(evaluation) == "rejected.alternate_series"
    assert evaluation.verdict["overrideable"] is True
    assert evaluation.legacy_match is None


def test_duplicate_candidate_is_blocked(monkeypatch):
    checker = search_filer.search_check()
    info = _info(manual=True)
    first = checker._process_entry(_entry(), info)
    comicarr.COMICINFO.append(first)

    duplicate = checker.evaluate_entry(_entry(), info)

    assert _reason(duplicate) == "blocked.duplicate"
    assert duplicate.verdict["overrideable"] is False


def test_unexpected_evaluator_error_is_structured_but_legacy_adapter_reraises():
    checker = search_filer.search_check()
    malformed = {"title": "Example Series 001"}

    evaluation = checker.evaluate_entry(malformed, _info())
    assert _reason(evaluation) == "error.evaluation_exception"
    assert evaluation.exception is not None

    with pytest.raises(type(evaluation.exception)):
        checker._process_entry(malformed, _info())


def test_evaluate_entries_returns_one_ordered_evaluation_per_raw_entry(monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _config(IGNORE_SEARCH_WORDS=["repack"]))
    entries = [
        _entry(id="accepted"),
        _entry(id="ignored", title="Example Series 001 REPACK"),
        {"title": "Malformed provider entry"},
    ]

    evaluations = search_filer.search_check().evaluate_entries(entries, _info())

    assert [_reason(evaluation) for evaluation in evaluations] == [
        "accepted.issue",
        "ignored.search_word",
        "error.evaluation_exception",
    ]


def test_automatic_adapter_preserves_legacy_shape_and_download_flag():
    match = search_filer.search_check()._process_entry(_entry(), _info(manual=False))

    assert match["downloadit"] is True
    assert match["pack"] is False
    assert "verdict" not in match
    assert "candidate" not in match


def test_checker_keeps_only_legacy_matches_and_populates_global(monkeypatch):
    checker = search_filer.search_check()
    entries = [_entry(id="one"), _entry(id="ignored", title="Example Series REPACK"), _entry(id="two", link="two")]
    monkeypatch.setattr(comicarr, "CONFIG", _config(IGNORE_SEARCH_WORDS=["repack"]))

    matches = checker.checker(entries, _info())

    assert [match["entry"]["id"] for match in matches] == ["one", "two"]
    assert comicarr.COMICINFO == matches


def test_first_result_preserves_preference_and_last_fallback(monkeypatch):
    checker = search_filer.search_check()
    candidates = [
        {"pack": True, "name": "first-pack"},
        {"pack": True, "name": "last-pack"},
        {"pack": False, "name": "preferred-issue"},
    ]
    process = MagicMock(side_effect=candidates)
    monkeypatch.setattr(checker, "_process_entry", process)

    assert checker.check_for_first_result([1, 2, 3], {}, prefer_pack=False)["name"] == "preferred-issue"
    assert process.call_count == 3

    process.reset_mock(side_effect=True)
    process.side_effect = candidates[:2]
    assert checker.check_for_first_result([1, 2], {}, prefer_pack=False)["name"] == "last-pack"


class TestMangaVolumeAcceptanceArm:
    """The volume-number acceptance arm, driven through evaluate_entry.

    The store-date tests above cannot reach it: they stub justthedigits as 1,
    so they accept via `intIss == comintIss` and the arm never runs. A volume
    release carries no issue digits at all, which is precisely the shape that
    reaches this arm.
    """

    @staticmethod
    def _evaluate(monkeypatch, *, volume, wanted, series_volume=None):
        _install_parser(
            monkeypatch,
            parsed=_parsed(series_volume=series_volume or "v%s" % volume, issue_number=None, booktype="TPB"),
            # No issue digits: a volume release has none, so pc_in is None,
            # and the volume itself is what the arm compares against.
            matched=_matched(
                justthedigits=None,
                booktype="TPB",
                volume=series_volume or "v%s" % volume,
                series_volume=series_volume or "v%s" % volume,
            ),
        )
        return search_filer.search_check().evaluate_entry(
            _entry(title="Example Series v%s (2024)" % volume),
            _info(
                manga_match_name="Example Series",
                findcomiciss=wanted,
                IssueNumber=wanted,
                cmloopit=3,
                UseFuzzy="0",
                booktype="TPB",
            ),
        )

    def test_the_wanted_volume_is_accepted(self, monkeypatch):
        evaluation = self._evaluate(monkeypatch, volume="06", wanted="6")
        assert _reason(evaluation) is None or "rejected" not in str(_reason(evaluation))

    def test_a_different_volume_is_rejected(self, monkeypatch):
        """The arm must discriminate, not wave every volume through."""
        evaluation = self._evaluate(monkeypatch, volume="07", wanted="6")
        assert "rejected" in str(_reason(evaluation))

    def test_a_three_digit_volume_is_still_read_as_a_volume(self, monkeypatch):
        """v100 is 3 digits after the v, so it is a volume and not a year.

        The version arm measured the whole `v100` string against `< 4`, so it
        matched no arm, left fndcomicversion None and lost the year bypass --
        One Piece v100 labelled 2021 against a 1997 series year was rejected.
        """
        evaluation = self._evaluate(monkeypatch, volume="100", wanted="100")
        assert _reason(evaluation) is None or "rejected" not in str(_reason(evaluation))
