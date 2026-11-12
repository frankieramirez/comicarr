#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The issue page's details: search history, attempts, log lines, import source."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

import comicarr
from comicarr import db, search
from comicarr.app.search import search_history
from comicarr.app.search.evaluation import EvaluationSession
from comicarr.app.series import issue_story
from comicarr.tables import activity_events, issues, metadata, pipeline_journal


@pytest.fixture
def story_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", SimpleNamespace())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.shutdown_engine()
    engine = db.get_engine()
    metadata.create_all(engine)
    yield engine
    db.shutdown_engine()


def _seen(title, status="accepted", reason="accepted.issue", provider="NZBgeek", size=68_000_000):
    return {
        "candidate": {"title": title, "provider": provider, "size_bytes": size, "pack": False},
        "verdict": {"status": status, "reason_code": reason, "reasons": [{"code": reason, "message": "m"}]},
    }


OBSERVED = [
    _seen("Absolute.Flash.018.2026.Digital.cbz"),
    _seen("Absolute.Flash.018.2026.HD.cbz", size=74_000_000),
    _seen("Absolute Flash 017", "rejected", "rejected.issue_mismatch"),
    _seen("Absolute Flash 016", "rejected", "rejected.issue_mismatch"),
    _seen("Flash 018", "rejected", "rejected.series_mismatch", provider="Prowlarr"),
]


def test_summary_counts_reasons_and_providers():
    summary = search_history.build_summary(OBSERVED)
    assert summary["total"] == 5
    assert summary["accepted_count"] == 2
    assert summary["rejected_count"] == 3
    assert summary["providers"] == ["NZBgeek", "Prowlarr"]
    assert summary["reasons"][0] == {"code": "rejected.issue_mismatch", "label": "wrong issue", "count": 2}


def test_record_replaces_the_previous_search(story_db):
    search_history.record("iss-18", OBSERVED, searched_at="2026-10-26T14:02:00+00:00")
    search_history.record("iss-18", OBSERVED[:1], searched_at="2026-10-27T14:02:00+00:00")
    saved = search_history.read("iss-18")
    assert saved["total"] == 1
    assert saved["searched_at"] == "2026-10-27T14:02:00+00:00"
    assert search_history.read("never") is None


def test_take_observed_copies_every_verdict_once():
    session = EvaluationSession()
    session._observed = [SimpleNamespace(as_dict=lambda: {"candidate": {}, "verdict": {}})]
    assert len(session.take_observed()) == 1
    assert session.take_observed() == []


def test_search_init_records_what_the_search_saw(story_db, monkeypatch):
    def fake(*args, **kwargs):
        kwargs["evaluator"]._observed = [SimpleNamespace(as_dict=lambda: OBSERVED[0])]
        return {"status": False}, "None"

    monkeypatch.setattr(search, "_search_init", fake)
    search.search_init("Absolute Flash", "18", "2026", "2024", "DC", "2026-08-19", "2026-08-19", "iss-18")
    assert search_history.read("iss-18")["accepted_count"] == 1


def test_an_empty_rss_pass_keeps_the_last_full_search(story_db, monkeypatch):
    search_history.record("iss-18", OBSERVED)
    monkeypatch.setattr(search, "_search_init", lambda *a, **k: ({"status": False}, "None"))
    search.search_init("Absolute Flash", "18", "2026", "2024", "DC", "", "", "iss-18", rsschecker="yes")
    assert search_history.read("iss-18")["total"] == 5


def test_story_details_counts_attempts_marks_the_chosen_release_and_finds_log_lines(story_db, tmp_path):
    with story_db.begin() as conn:
        conn.execute(insert(issues).values(IssueID="iss-18", ComicName="Absolute Flash", Issue_Number="18"))
        conn.execute(
            insert(pipeline_journal).values(
                release_key="rk-18",
                issueid="iss-18",
                provider="NZBgeek",
                nzbname="Absolute.Flash.018.2026.Digital",
                stage="manual_review",
                stage_rank=70,
                payload_json=json.dumps({"nzb_folder": "/data/usenet/complete/comics"}),
                fail_reason="sab_completed_file_not_found",
                updated_date="2026-10-26 14:09:02",
            )
        )
        for activity in ("search", "grab", "download", "import", "import"):
            conn.execute(
                insert(activity_events).values(
                    created_at="2026-10-26T14:02:00+00:00",
                    activity=activity,
                    status="failed" if activity == "import" else "succeeded",
                    subject_type="issue",
                    subject_id="iss-18",
                    subject_label="Absolute Flash #18",
                )
            )
    search_history.record("iss-18", OBSERVED)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "comicarr.log").write_text(
        "26-Oct-2026 14:09:02 - INFO    :: postprocess : Absolute.Flash.018.2026.Digital not found\n"
        "26-Oct-2026 14:09:01 - INFO    :: postprocess : scanning for Absolute Flash #18\n"
        "26-Oct-2026 14:09:03 - INFO    :: other : Saga #75 done\n"
    )
    ctx = SimpleNamespace(config=SimpleNamespace(LOG_DIR=str(log_dir), LOG_LEVEL=1), data_dir=str(tmp_path))

    details = issue_story.story_details(ctx, "iss-18")

    assert details["attempts"] == {"search": 1, "grab": 1, "download": 1, "import": 2}
    chosen = [row["title"] for row in details["search"]["accepted"] if row["chosen"]]
    assert chosen == ["Absolute.Flash.018.2026.Digital.cbz"]
    lines = details["log"]["lines"]
    assert len(lines) == 2
    assert lines[0].endswith("scanning for Absolute Flash #18")
    assert lines[1].endswith("Absolute.Flash.018.2026.Digital not found")
    assert "Saga" not in "".join(details["log"]["lines"])


def test_story_details_without_history_is_empty(story_db, tmp_path):
    ctx = SimpleNamespace(config=SimpleNamespace(LOG_DIR=str(tmp_path / "none")), data_dir=str(tmp_path))
    details = issue_story.story_details(ctx, "iss-1")
    assert details["search"] is None
    assert details["log"]["lines"] == []


def test_import_source_reads_the_waiting_download(story_db):
    from comicarr.app.attention import router as attention_router

    with story_db.begin() as conn:
        conn.execute(
            insert(pipeline_journal).values(
                release_key="rk-18",
                issueid="iss-18",
                nzbname="Absolute.Flash.018.2026.Digital",
                stage="manual_review",
                stage_rank=70,
                payload_json=json.dumps({"nzb_folder": "/data/usenet/complete/comics"}),
                updated_date="2026-10-26 14:09:02",
            )
        )
    assert attention_router.get_import_source("rk-18") == {
        "release_key": "rk-18",
        "nzb_name": "Absolute.Flash.018.2026.Digital",
        "nzb_folder": "/data/usenet/complete/comics",
    }
    assert attention_router.get_import_source("missing").status_code == 404
