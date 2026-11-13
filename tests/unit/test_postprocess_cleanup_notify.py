#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Cleanup and notification stages of post-processing (#1218).

Cleanup removes what ``FILE_OPTS`` allows and nothing else, and a cleanup
failure never undoes a completed release. Notification is sent once: only the
call that wrote ``post_processed`` notifies, so a recovery re-run is silent.
"""

import shutil
import types

import pytest
from sqlalchemy import insert, select

import comicarr
from comicarr.app.downloads import journal
from comicarr.app.downloads._postprocess_completion import complete
from comicarr.app.downloads.postprocess_pipeline import (
    PostProcessCleanupContext,
    PostProcessCleanupStage,
    PostProcessContext,
    PostProcessNotification,
    PostProcessNotifyStage,
)
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import metadata, nzblog, pipeline_journal

# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


class _Log:
    def __init__(self):
        self.lines = []

    def _record(self, message):
        self.lines.append(message)

    fdebug = info = warn = error = _record


def _cleanup_context(folder, *, file_opts="move", nzb_name="Saga.001.cbz", issue_id=None, **overrides):
    values = dict(
        nzb_folder=str(folder),
        nzb_name=nzb_name,
        issue_id=issue_id,
        file_opts=file_opts,
        enable_meta=False,
        ddl_location=None,
    )
    values.update(overrides)
    return PostProcessCleanupContext(**values)


def _stage():
    narrated = []
    return PostProcessCleanupStage(narrate=narrated.append, log=_Log()), narrated


def test_move_removes_the_placed_file_and_its_now_empty_folder(tmp_path):
    folder = tmp_path / "Saga.001"
    folder.mkdir()
    (folder / "Saga 001.cbz").write_bytes(b"x")
    stage, narrated = _stage()

    stage.tidy(_cleanup_context(folder), del_nzbdir=True, filename="Saga 001.cbz")

    assert not folder.exists()
    assert any("Removed temporary directory" in line for line in narrated)


def test_move_leaves_other_files_and_their_folder_alone(tmp_path):
    folder = tmp_path / "Saga.001"
    folder.mkdir()
    (folder / "Saga 001.cbz").write_bytes(b"x")
    (folder / "Saga 002.cbz").write_bytes(b"y")
    stage, _ = _stage()

    stage.tidy(_cleanup_context(folder), del_nzbdir=True, filename="Saga 001.cbz")

    assert sorted(p.name for p in folder.iterdir()) == ["Saga 002.cbz"]


@pytest.mark.parametrize("file_opts", ["copy", "hardlink", "softlink"])
def test_non_move_modes_remove_no_download_files(tmp_path, file_opts):
    folder = tmp_path / "Saga.001"
    folder.mkdir()
    (folder / "Saga 001.cbz").write_bytes(b"x")
    stage, _ = _stage()

    stage.tidy(_cleanup_context(folder, file_opts=file_opts), del_nzbdir=True, filename="Saga 001.cbz")

    assert (folder / "Saga 001.cbz").exists()


def test_move_without_del_nzbdir_keeps_the_download(tmp_path):
    folder = tmp_path / "Saga.001"
    folder.mkdir()
    (folder / "Saga 001.cbz").write_bytes(b"x")
    stage, _ = _stage()

    stage.tidy(_cleanup_context(folder), del_nzbdir=False, filename="Saga 001.cbz")

    assert (folder / "Saga 001.cbz").exists()


def test_mega_ddl_folder_is_kept_after_its_file_goes(tmp_path):
    mega = tmp_path / "mega"
    mega.mkdir()
    (mega / "Saga 001.cbz").write_bytes(b"x")
    stage, _ = _stage()

    stage.tidy(
        _cleanup_context(mega, ddl_location=str(tmp_path)),
        del_nzbdir=True,
        filename="Saga 001.cbz",
    )

    assert mega.is_dir()
    assert not (mega / "Saga 001.cbz").exists()


def test_manual_run_removes_only_the_named_file_from_the_watch_folder(tmp_path):
    (tmp_path / "Saga 001.cbz").write_bytes(b"x")
    (tmp_path / "Other 001.cbz").write_bytes(b"y")
    stage, _ = _stage()

    stage.tidy(_cleanup_context(tmp_path, nzb_name="Manual Run"), filename="Saga 001.cbz")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["Other 001.cbz"]


def test_metadata_cache_folder_goes_when_tagging_made_one(tmp_path):
    cache = tmp_path / "comicarr_abc123"
    cache.mkdir()
    (cache / "tagged.cbz").write_bytes(b"x")
    stage, _ = _stage()

    stage.tidy(_cleanup_context(tmp_path, enable_meta=True), odir=str(cache), cacheonly=True)

    assert not cache.exists()


def test_a_folder_not_named_as_a_cache_is_never_emptied(tmp_path):
    library = tmp_path / "Saga (2012)"
    library.mkdir()
    (library / "Saga 001.cbz").write_bytes(b"x")
    stage, _ = _stage()

    stage.tidy(_cleanup_context(tmp_path, enable_meta=True), odir=str(library), cacheonly=True)

    assert (library / "Saga 001.cbz").exists()


def test_cache_folder_is_left_when_tagging_is_off(tmp_path):
    cache = tmp_path / "comicarr_abc123"
    cache.mkdir()
    (cache / "tagged.cbz").write_bytes(b"x")
    stage, _ = _stage()

    stage.tidy(_cleanup_context(tmp_path, enable_meta=False), odir=str(cache), cacheonly=True)

    assert (cache / "tagged.cbz").exists()


def test_cleanup_failure_is_narrated_not_raised(tmp_path, monkeypatch):
    folder = tmp_path / "Saga.001"
    folder.mkdir()

    def _boom(_path):
        raise OSError("device busy")

    monkeypatch.setattr(shutil, "rmtree", _boom)
    stage, narrated = _stage()

    stage.tidy(_cleanup_context(folder), del_nzbdir=True, filename="Saga 001.cbz")

    assert folder.exists()
    assert "Failed to remove temporary directory" in narrated


# ---------------------------------------------------------------------------
# notification
# ---------------------------------------------------------------------------


def _config(**enabled):
    names = (
        "PROWL",
        "PUSHOVER",
        "BOXCAR",
        "PUSHBULLET",
        "TELEGRAM",
        "SLACK",
        "MATTERMOST",
        "DISCORD",
        "EMAIL",
        "GOTIFY",
        "MATRIX",
    )
    values = {"%s_ENABLED" % name: False for name in names}
    values.update(PUSHOVER_IMAGE=False, TELEGRAM_IMAGE=False, EMAIL_ONPOST=False)
    values.update(enabled)
    return types.SimpleNamespace(**values)


class _Notifiers:
    """Stands in for ``comicarr.app.notifications.service``."""

    def __init__(self, fail=False):
        self.sent = []
        self._fail = fail

    def __getattr__(self, name):
        if not name.isupper():
            raise AttributeError(name)
        sent = self.sent
        fail = self._fail

        class _Client:
            def notify(self, *args, **kwargs):
                if fail:
                    raise RuntimeError("notifier down")
                sent.append((name, args, kwargs))

        return _Client


def _item(**overrides):
    values = dict(
        series="Saga",
        issue_year="2012",
        issue_number="1",
        placed_path="/library/Saga (2012)/Saga 001.cbz",
        issue_id="I1",
    )
    values.update(overrides)
    return PostProcessNotification(**values)


def _notify_stage(config, notifiers, covers=None):
    def _extract(path, **kwargs):
        if covers is not None:
            covers.append(path)
        return {"ComicImage": "cover-bytes"}

    return PostProcessNotifyStage(extract_cover=_extract, notifiers=notifiers, config=config, log=_Log())


def test_completed_release_notifies_each_enabled_notifier_once():
    notifiers = _Notifiers()
    stage = _notify_stage(_config(SLACK_ENABLED=True, EMAIL_ENABLED=True, EMAIL_ONPOST=True), notifiers)

    assert stage.notify(_item(), completed=True) is True

    assert [name for name, _, _ in notifiers.sent] == ["SLACK", "EMAIL"]
    _, args, _ = notifiers.sent[0]
    assert args[1] == "Comicarr has downloaded and post-processed: Saga (2012) #1"


def test_email_needs_on_post_as_well_as_enabled():
    notifiers = _Notifiers()
    _notify_stage(_config(EMAIL_ENABLED=True, EMAIL_ONPOST=False), notifiers).notify(_item(), completed=True)

    assert notifiers.sent == []


def test_release_not_completed_by_this_call_sends_nothing():
    notifiers = _Notifiers()
    covers = []
    stage = _notify_stage(_config(SLACK_ENABLED=True, DISCORD_ENABLED=True), notifiers, covers)

    assert stage.notify(_item(), completed=False) is False

    assert notifiers.sent == []
    assert covers == []


def test_cover_is_read_from_the_placed_file_only_for_image_notifiers():
    covers = []
    notifiers = _Notifiers()
    _notify_stage(_config(SLACK_ENABLED=True), notifiers, covers).notify(_item(), completed=True)
    assert covers == []

    _notify_stage(_config(DISCORD_ENABLED=True), notifiers, covers).notify(_item(), completed=True)
    assert covers == ["/library/Saga (2012)/Saga 001.cbz"]
    _, _, kwargs = notifiers.sent[-1]
    assert kwargs["imageFile"] == "cover-bytes"


def test_issue_number_already_marked_is_not_marked_twice():
    notifiers = _Notifiers()
    _notify_stage(_config(PROWL_ENABLED=True), notifiers).notify(
        _item(issue_year=None, issue_number="#5"), completed=True
    )

    assert notifiers.sent[0][1][0] == "Saga #5"


def test_notifier_failure_is_logged_not_raised():
    stage = _notify_stage(_config(SLACK_ENABLED=True), _Notifiers(fail=True))

    assert stage.notify(_item(), completed=True) is False


# ---------------------------------------------------------------------------
# through the real journal: one notification, and cleanup cannot undo completion
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if getattr(comicarr, "LOG_LEVEL", None) is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
    metadata.create_all(get_engine())
    yield
    shutdown_engine()


def _pp_context(release_key="rk-1218"):
    return PostProcessContext(
        issue_id="I1218",
        issue_arc_id=None,
        comic_id="C1218",
        nzb_name="Saga.001.cbz",
        nzb_folder="/downloads/Saga.001",
        api_call=False,
        ddl=False,
        canonical_release_key=release_key,
        log_module="[POST-PROCESSING]",
    )


def _stage_of(release_key):
    with get_engine().connect() as conn:
        row = conn.execute(select(pipeline_journal.c.stage).where(pipeline_journal.c.release_key == release_key))
        found = row.fetchone()
    return found[0] if found else None


@pytest.mark.usefixtures("_isolated_db")
def test_recover_rerun_after_completion_sends_no_second_notification():
    context = _pp_context()
    journal.record_transition(context.canonical_release_key, journal.POST_PROCESSING, issueid="I1218")
    journal.record_transition(context.canonical_release_key, journal.MOVED, issueid="I1218")
    with get_engine().begin() as conn:
        conn.execute(insert(nzblog).values(IssueID="I1218", NZBName="Saga.001.cbz"))

    notifiers = _Notifiers()
    stage = _notify_stage(_config(SLACK_ENABLED=True), notifiers)

    first = complete(context, issue_id="I1218", anchor_ids=("I1218",))
    stage.notify(_item(issue_id="I1218"), completed=first.recorded)

    # A restart re-drives the same release: completion finds it already done.
    second = complete(context, issue_id="I1218", anchor_ids=("I1218",))
    stage.notify(_item(issue_id="I1218"), completed=second.recorded)

    assert first.recorded is True
    assert second.recorded is False
    assert len(notifiers.sent) == 1
    assert _stage_of(context.canonical_release_key) == journal.POST_PROCESSED


@pytest.mark.usefixtures("_isolated_db")
def test_cleanup_failure_leaves_the_release_completed(tmp_path, monkeypatch):
    context = _pp_context()
    journal.record_transition(context.canonical_release_key, journal.POST_PROCESSING, issueid="I1218")
    journal.record_transition(context.canonical_release_key, journal.MOVED, issueid="I1218")

    folder = tmp_path / "Saga.001"
    folder.mkdir()

    def _boom(_path):
        raise OSError("device busy")

    monkeypatch.setattr(shutil, "rmtree", _boom)
    cleanup, narrated = _stage()
    cleanup.tidy(_cleanup_context(folder), del_nzbdir=True, filename="Saga 001.cbz")

    result = complete(context, issue_id="I1218", anchor_ids=("I1218",))

    assert "Failed to remove temporary directory" in narrated
    assert result.recorded is True
    assert _stage_of(context.canonical_release_key) == journal.POST_PROCESSED
