#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import os
import tracemalloc
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from comicarr.app.core.context import get_context
from comicarr.app.core.security import require_session
from comicarr.app.system import log_files, service
from comicarr.app.system.router import router


@pytest.fixture
def log_ctx(tmp_path):
    return SimpleNamespace(
        data_dir=str(tmp_path),
        config=SimpleNamespace(LOG_DIR=str(tmp_path), LOG_LEVEL=1, EXTRA_NEWZNABS=[], EXTRA_TORZNABS=[]),
    )


def test_current_and_retained_files_search_both_formats_and_whole_traceback(log_ctx, tmp_path):
    contents = (
        "unknown startup line\n"
        "11-Aug-2026 14:28:01 - INFO    :: comicarr.search.12 : MainThread : needle\n"
        "11-Aug-2026 14:28:02 - ERROR   :: MainThread : search.py:search:13 : failed\n"
        "Traceback (most recent call last):\n"
        "  RuntimeError: NEEDLE\n"
        "11-Aug-2026 14:28:03 - ERROR   :: comicarr.backup.14 : MainThread : needle\n"
    )
    (tmp_path / "comicarr.log").write_text(contents)
    (tmp_path / "comicarr.log.2").write_text(contents)
    files = service.list_log_files(log_ctx)["files"]
    assert [entry["name"] for entry in files] == ["comicarr.log", "comicarr.log.2"]
    assert all(entry["size"] > 0 and entry["modified"] for entry in files)
    for entry in files:
        result = service.search_logs(
            log_ctx, selector=entry["selector"], query="needle", component="search", severity="ERROR"
        )
        assert result["logs"] == contents.splitlines(keepends=True)[2:5]
        assert result["file"]["name"] == entry["name"]
        assert result["lines_scanned"] == 6
        assert result["records_matched"] == result["records_returned"] == 1
        assert result["truncated"] is False


@pytest.fixture
def log_app(log_ctx):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_context] = lambda: log_ctx
    return app


def test_authenticated_api_keeps_legacy_tail_and_adds_selected_search(log_app, tmp_path):
    header = "11-Aug-2026 14:28:01 - INFO :: comicarr.search.12 : MainThread : "
    (tmp_path / "comicarr.log").write_text(header + "old match\n" + (header + "newer\n") * 6000)
    log_app.dependency_overrides[require_session] = lambda: "operator"
    with TestClient(log_app) as client:
        files = client.get("/api/system/logs/files")
        assert files.status_code == 200
        selector = files.json()["files"][0]["selector"]
        legacy = client.get("/api/system/logs?lines=3").json()
        assert legacy["logs"] == [header + "newer\n"] * 3
        search = client.get("/api/system/logs", params={"selector": selector, "query": "old match", "lines": 3})
        assert search.status_code == 200
        assert search.json()["lines_scanned"] == 6001
        assert search.json()["logs"] == [header + "old match\n"]


def test_newest_matches_are_capped_chronological_and_redacted(log_ctx, tmp_path):
    secret = "canary-provider-key-1015"
    log_ctx.config.EXTRA_TORZNABS = [("indexer", "https://example.test", "1", secret)]
    (tmp_path / "comicarr.log.2").write_text(
        "".join(
            f"11-Aug-2026 14:28:0{n} - ERROR :: comicarr.search.12 : MainThread : match-{n} {secret}\n  detail-{n}\n"
            for n in range(5)
        )
    )
    result = service.search_logs(log_ctx, selector="rotation-2", limit=2)
    text = "".join(result["logs"])
    assert secret not in text
    assert "match-2" not in text
    assert text.index("match-3") < text.index("match-4")
    assert "detail-3" in text and "detail-4" in text
    assert result["records_matched"] == 5
    assert result["records_returned"] == 2
    assert result["truncated"] is True


@pytest.mark.parametrize(
    "filters, expected",
    [
        ({}, "unknown startup"),
        ({"query": "[literal].*"}, "[literal].*"),
        ({"severity": "DEBUG"}, "known info"),
        ({"component": "SEARCH"}, "known info"),
    ],
)
def test_unknown_records_and_literal_query(log_ctx, tmp_path, filters, expected):
    (tmp_path / "comicarr.log").write_text(
        "unknown startup [literal].*\n"
        "11-Aug-2026 14:28:01 - MYSTERY :: unfamiliar : unknown header\n"
        "11-Aug-2026 14:28:02 - INFO :: comicarr.search.12 : MainThread : known info\n"
    )
    text = "".join(service.search_logs(log_ctx, **filters)["logs"])
    assert expected in text
    if "severity" in filters or "component" in filters:
        assert "unknown" not in text
    if "query" in filters:
        assert "known info" not in text


@pytest.mark.parametrize(
    "url",
    [
        "/api/system/logs/files",
        "/api/system/logs?selector=current",
        "/api/system/logs?lines=2",
        "/api/system/logs/download?selector=current",
    ],
)
def test_log_reads_require_session(log_app, url):
    with TestClient(log_app) as client:
        assert client.get(url).status_code == 401


@pytest.mark.parametrize(
    "selector",
    [
        "../comicarr.log",
        "/tmp/comicarr.log",
        "comicarr.log",
        "unknown",
        "rotation-0",
        "rotation-2/../comicarr.log",
        "rotation-2\\..\\comicarr.log",
        "rotation-2%2f..%2fcomicarr.log",
        "rotation-2\x00",
        "rotation-2\n",
        "rotation-２",
        "",
    ],
)
@pytest.mark.parametrize("endpoint", ["/api/system/logs", "/api/system/logs/download"])
def test_api_refuses_paths_and_unknown_selectors(log_app, selector, endpoint):
    log_app.dependency_overrides[require_session] = lambda: "operator"
    with TestClient(log_app) as client:
        response = client.get(endpoint, params={"selector": selector})
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_selector"


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
@pytest.mark.parametrize("selector, name", [("current", "comicarr.log"), ("rotation-2", "comicarr.log.2")])
def test_unsafe_files_are_not_listed_or_read(log_ctx, tmp_path, kind, selector, name):
    path = tmp_path / name
    if kind == "symlink":
        target = tmp_path / "secret.txt"
        target.write_text("secret outside logs")
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    assert service.list_log_files(log_ctx)["files"] == []
    with pytest.raises(log_files.LogFileError) as error:
        service.search_logs(log_ctx, selector=selector)
    assert error.value.code == "unsafe_file"
    with pytest.raises(log_files.LogFileError) as error:
        service.download_log(log_ctx, selector)
    assert error.value.code == "unsafe_file"


def test_missing_and_unreadable_files_are_actionable(log_app, tmp_path, monkeypatch):
    log_app.dependency_overrides[require_session] = lambda: "operator"
    with TestClient(log_app) as client:
        response = client.get("/api/system/logs?selector=rotation-2")
        assert response.status_code == 404
        assert response.json()["code"] == "missing"
        assert "Refresh" in response.json()["error"]
        (tmp_path / "comicarr.log.2").write_text("contents\n")
        with monkeypatch.context() as patch:
            patch.setattr(log_files.os, "open", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError()))
            response = client.get("/api/system/logs?selector=rotation-2")
        assert response.status_code == 503
        assert response.json()["code"] == "unreadable"
        assert "Refresh" in response.json()["error"]


@pytest.mark.parametrize(
    "endpoint, function",
    [
        ("/api/system/logs?selector=current", "search_logs"),
        ("/api/system/logs/files", "list_log_files"),
        ("/api/system/logs/download?selector=current", "download_log"),
    ],
)
@pytest.mark.parametrize(
    "code, status, public_code",
    [
        ("invalid_selector", 400, "invalid_selector"),
        ("unsafe_file", 400, "unsafe_file"),
        ("missing", 404, "missing"),
        ("changed", 409, "changed"),
        ("too_large", 413, "too_large"),
        ("unreadable", 503, "unreadable"),
        ("PRIVATE token=canary-secret", 503, "unreadable"),
    ],
)
def test_log_errors_never_serialize_exception_details(
    log_app, monkeypatch, endpoint, function, code, status, public_code
):
    log_app.dependency_overrides[require_session] = lambda: "operator"

    def fail(*args, **kwargs):
        raise log_files.LogFileError(code, "PRIVATE /credentials/provider.key token=canary-secret")

    monkeypatch.setattr(service, function, fail)
    with TestClient(log_app) as client:
        response = client.get(endpoint)
    assert response.status_code == status
    assert response.json()["code"] == public_code
    assert "PRIVATE" not in response.text
    assert "/credentials" not in response.text
    assert "canary-secret" not in response.text


def test_legacy_tail_errors_never_serialize_exception_details(log_app, tmp_path, monkeypatch):
    (tmp_path / "comicarr.log").write_text("contents\n")
    log_app.dependency_overrides[require_session] = lambda: "operator"

    def fail(*args, **kwargs):
        raise PermissionError("PRIVATE /credentials/provider.key token=canary-secret")

    monkeypatch.setattr(service, "open", fail, raising=False)
    with TestClient(log_app) as client:
        response = client.get("/api/system/logs?lines=2")
    assert response.status_code == 200
    assert response.json()["logs"] == []
    assert "Refresh" in response.json()["error"]
    assert "PRIVATE" not in response.text
    assert "/credentials" not in response.text
    assert "canary-secret" not in response.text


def test_selected_missing_current_log_remains_actionable(log_app):
    log_app.dependency_overrides[require_session] = lambda: "operator"
    with TestClient(log_app) as client:
        legacy = client.get("/api/system/logs?lines=2")
        selected = client.get("/api/system/logs?selector=current")
    assert legacy.status_code == 200
    assert legacy.json()["logs"] == []
    assert selected.status_code == 404
    assert selected.json()["code"] == "missing"
    assert "Refresh" in selected.json()["error"]


def test_rotation_during_read_returns_changed_error(log_ctx, tmp_path, monkeypatch):
    path = tmp_path / "comicarr.log"
    path.write_text("old contents\n")
    original = log_files.redact_sensitive_text

    def rotate(line, secrets):
        path.rename(tmp_path / "comicarr.log.1")
        path.write_text("new contents\n")
        return original(line, secrets)

    monkeypatch.setattr(log_files, "redact_sensitive_text", rotate)
    with pytest.raises(log_files.LogFileError) as error:
        service.search_logs(log_ctx)
    assert error.value.code == "changed"


def test_file_disappearing_during_scan_reports_rotation(log_ctx, tmp_path, monkeypatch):
    path = tmp_path / "comicarr.log"
    path.write_text("contents\n")
    original = log_files.redact_sensitive_text

    def disappear(line, secrets):
        path.unlink()
        return original(line, secrets)

    monkeypatch.setattr(log_files, "redact_sensitive_text", disappear)
    with pytest.raises(log_files.LogFileError) as error:
        service.search_logs(log_ctx)
    assert error.value.code == "changed"


def test_byte_cap_returns_only_newest_whole_records(log_ctx, tmp_path):
    line = "11-Aug-2026 14:28:01 - INFO :: comicarr.search.12 : MainThread : " + "x" * 600000 + "\n"
    (tmp_path / "comicarr.log").write_text(line * 15)
    result = service.search_logs(log_ctx)
    assert result["records_matched"] == 15
    assert result["records_returned"] == 13
    assert result["truncated"] is True
    assert result["logs"] == [line] * 13


@pytest.mark.parametrize("contents", ["x" * (1024 * 1024 + 1), "small continuation\n" * 500000])
def test_oversized_line_or_whole_record_errors_instead_of_partial_output(log_ctx, tmp_path, contents):
    (tmp_path / "comicarr.log").write_text(contents)
    with pytest.raises(log_files.LogFileError) as error:
        service.search_logs(log_ctx)
    assert error.value.code == "too_large"


def test_search_memory_does_not_grow_with_file_size(log_ctx, tmp_path):
    path = tmp_path / "comicarr.log"
    with path.open("w") as source:
        for _ in range(30000):
            source.write("11-Aug-2026 14:28:01 - INFO :: comicarr.search.12 : MainThread : " + "x" * 600 + "\n")
    tracemalloc.start()
    try:
        result = service.search_logs(log_ctx, query="absent")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result["lines_scanned"] == 30000
    assert result["records_returned"] == 0
    assert peak < 2 * 1024 * 1024


PLANTED_SECRETS = (
    "canary-api-key-1016",
    "canary-query-key-1016",
    "canary-url-password-1016",
    "canary-bearer-1016",
    "canary-tuple-1016",
    "canary-provider-key-1016",
)


def _planted_log():
    return (
        "11-Aug-2026 14:28:01 - INFO :: comicarr.search.12 : MainThread : api_key=canary-api-key-1016\n"
        "11-Aug-2026 14:28:02 - DEBUG :: comicarr.search.12 : MainThread : GET https://indexer.test/api?t=search&apikey=canary-query-key-1016\n"
        "11-Aug-2026 14:28:03 - INFO :: comicarr.sabnzbd.12 : MainThread : https://operator:canary-url-password-1016@sab.test/api\n"
        "11-Aug-2026 14:28:04 - DEBUG :: comicarr.search.12 : MainThread : headers {'Authorization': 'Bearer canary-bearer-1016'}\n"
        "11-Aug-2026 14:28:05 - DEBUG :: comicarr.search.12 : MainThread : provider_list: ['nzb', 'canary-tuple-1016']\n"
        "11-Aug-2026 14:28:06 - ERROR :: comicarr.search.12 : MainThread : indexer rejected canary-provider-key-1016\n"
        "Traceback (most recent call last):\n"
        "  RuntimeError: Batman 2016 /comics/Batman (2016)\n"
    )


@pytest.mark.parametrize("selector, name", [("current", "comicarr.log"), ("rotation-2", "comicarr.log.2")])
def test_download_streams_whole_file_line_for_line_redacted(log_app, log_ctx, tmp_path, selector, name):
    log_ctx.config.EXTRA_NEWZNABS = [("indexer", "https://indexer.test", "1", "canary-provider-key-1016")]
    (tmp_path / name).write_text(_planted_log())
    log_app.dependency_overrides[require_session] = lambda: "operator"
    with TestClient(log_app) as client:
        response = client.get("/api/system/logs/download", params={"selector": selector})
    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'attachment; filename="{name}.redacted.txt"'
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"
    lines = response.text.splitlines(keepends=True)
    assert len(lines) == len(_planted_log().splitlines())
    assert lines[-1] == "  RuntimeError: Batman 2016 /comics/Batman (2016)\n"
    assert all("[redacted]" in line for line in lines[:6])
    for secret in PLANTED_SECRETS:
        assert secret not in response.text


def test_download_is_a_bounded_memory_iterator(log_ctx, tmp_path):
    path = tmp_path / "comicarr.log"
    line = "11-Aug-2026 14:28:01 - INFO :: comicarr.search.12 : MainThread : " + "x" * 600 + "\n"
    with path.open("w") as source:
        for _ in range(30000):
            source.write(line)
    name, chunks = service.download_log(log_ctx, "current")
    assert name == "comicarr.log"
    assert iter(chunks) is chunks
    tracemalloc.start()
    try:
        total = count = 0
        for chunk in chunks:
            total += len(chunk)
            count += 1
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert total == path.stat().st_size
    assert count > 100
    assert peak < 2 * 1024 * 1024


@pytest.mark.parametrize("change", ["unlink", "rotate", "truncate"])
def test_download_ends_with_visible_error_when_file_changes_mid_stream(log_ctx, tmp_path, monkeypatch, change):
    path = tmp_path / "comicarr.log"
    path.write_text("first line\n" + "later line\n" * 20000)
    original = log_files.redact_sensitive_text
    changed = False

    def mutate(line, secrets):
        nonlocal changed
        if not changed:
            changed = True
            if change == "unlink":
                path.unlink()
            elif change == "rotate":
                path.rename(tmp_path / "comicarr.log.1")
                path.write_text("new contents\n")
            else:
                os.truncate(path, 0)
        return original(line, secrets)

    monkeypatch.setattr(log_files, "redact_sensitive_text", mutate)
    _, chunks = service.download_log(log_ctx, "current")
    received = list(chunks)
    assert (
        received[-1]
        == b"\n[Comicarr] DOWNLOAD INCOMPLETE: The log file changed or disappeared during the download. Download it again.\n"
    )
    assert all(b"INCOMPLETE" not in chunk for chunk in received[:-1])


def test_download_api_ends_a_short_file_with_the_incomplete_marker(log_app, tmp_path, monkeypatch):
    path = tmp_path / "comicarr.log"
    path.write_text("first line\nsecond line\n")
    original = log_files.redact_sensitive_text

    def disappear(line, secrets):
        if path.exists():
            path.unlink()
        return original(line, secrets)

    monkeypatch.setattr(log_files, "redact_sensitive_text", disappear)
    log_app.dependency_overrides[require_session] = lambda: "operator"
    with TestClient(log_app) as client:
        response = client.get("/api/system/logs/download", params={"selector": "current"})
    assert response.status_code == 200
    assert response.text.endswith(
        "[Comicarr] DOWNLOAD INCOMPLETE: The log file changed or disappeared during the download. Download it again.\n"
    )


def test_download_refuses_oversized_lines_instead_of_splitting_secrets(log_ctx, tmp_path):
    (tmp_path / "comicarr.log").write_text("x" * (1024 * 1024 + 1))
    _, chunks = service.download_log(log_ctx, "current")
    assert list(chunks) == [
        b"\n[Comicarr] DOWNLOAD INCOMPLETE: A log line exceeds 1 MiB and cannot be redacted safely.\n"
    ]


def test_download_read_error_ends_with_marker_without_exception_detail(log_ctx, tmp_path, monkeypatch):
    (tmp_path / "comicarr.log").write_text("first line\n")
    _, chunks = service.download_log(log_ctx, "current")

    def fail(*args, **kwargs):
        raise PermissionError("PRIVATE /credentials/provider.key")

    monkeypatch.setattr(log_files, "redact_sensitive_text", fail)
    text = b"".join(chunks).decode()
    assert text == "\n[Comicarr] DOWNLOAD INCOMPLETE: Cannot read the selected log file. Check permissions.\n"
