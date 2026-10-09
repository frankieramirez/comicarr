#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import os
import re
import stat
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from comicarr.app.common.redaction import redact_sensitive_text

MAX_LOG_RECORDS = 5000
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
HEADER = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2} - ([A-Z]+)\s*:: (.*)")
SEVERITIES = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
    "EXCEPTION": 40,
    "CRITICAL": 50,
    "FATAL": 50,
}


class LogFileError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _filename(log_dir, selector):
    if selector == "current":
        return "comicarr.log"
    if not re.fullmatch(r"rotation-[1-9][0-9]{0,8}", selector):
        raise LogFileError("invalid_selector", "Unknown log file selector. Refresh the file list.")
    if log_dir:
        with os.scandir(log_dir) as entries:
            for entry in entries:
                if re.fullmatch(r"comicarr\.log\.[1-9][0-9]{0,8}", entry.name):
                    if "rotation-" + entry.name.removeprefix("comicarr.log.") == selector:
                        return entry.name
    raise LogFileError("missing", "The log file no longer exists. Refresh the file list.")


def _entry(name, info):
    return {
        "selector": "current" if name == "comicarr.log" else "rotation-" + name.removeprefix("comicarr.log."),
        "name": name,
        "size": info.st_size,
        "modified": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
    }


def list_files(log_dir):
    if not log_dir:
        return {"files": []}
    try:
        files = []
        with os.scandir(log_dir) as entries:
            for entry in entries:
                if not re.fullmatch(r"comicarr\.log(?:\.[1-9][0-9]{0,8})?", entry.name):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    files.append(_entry(entry.name, info))
        files.sort(key=lambda entry: 0 if entry["selector"] == "current" else int(entry["selector"].split("-")[1]))
        return {"files": files}
    except FileNotFoundError:
        return {"files": []}
    except OSError as e:
        raise LogFileError("unreadable", "Cannot list log files. Check directory permissions and Refresh.") from e


def _component(body):
    current = re.match(r"comicarr\.([^ :]+)\s*:", body)
    if current:
        return re.sub(r"\.\d+$", "", current[1])
    legacy = re.match(r"[^:]+ : [^:]+\.py:([^:]+):\d+ :", body)
    return legacy[1] if legacy else None


def _open(log_dir, selector):
    name = _filename(log_dir, selector)
    if not log_dir:
        raise LogFileError("missing", "The log file no longer exists. Refresh the file list.")
    path = Path(log_dir) / name
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise LogFileError("unsafe_file", "The selected log is not a regular file. Refresh the file list.")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    source = os.fdopen(fd, "rb")
    opened = os.fstat(source.fileno())
    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
        source.close()
        raise LogFileError("changed", "The log file changed during rotation. Refresh and search again.")
    return name, path, source, opened


def _check_unchanged(path, opened):
    try:
        after = path.lstat()
    except FileNotFoundError as e:
        raise LogFileError("changed", "The log file disappeared during rotation. Refresh and search again.") from e
    if (
        (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
        or after.st_size < opened.st_size
        or (after.st_size == opened.st_size and after.st_mtime_ns != opened.st_mtime_ns)
    ):
        raise LogFileError("changed", "The log file changed during rotation. Refresh and search again.")


def search_file(log_dir, selector, query="", component="", severity=None, limit=200, provider_secrets=()):
    limit = max(1, min(limit, MAX_LOG_RECORDS))
    query = query.casefold()
    component = component.casefold().removeprefix("comicarr.")
    floor = SEVERITIES.get(severity) if severity else None
    try:
        name, path, source, opened = _open(log_dir, selector)
        with source:
            records = deque(maxlen=limit)
            matched = scanned = 0
            start = position = 0
            record_severity = record_component = None
            text_match = not query

            def finish(end):
                nonlocal matched
                if (
                    end > start
                    and text_match
                    and (floor is None or (record_severity or 0) >= floor)
                    and (not component or record_component == component)
                ):
                    matched += 1
                    records.append((start, end))

            while position < opened.st_size:
                raw = source.readline(min(MAX_LINE_BYTES + 1, opened.st_size - position))
                if not raw:
                    raise LogFileError("changed", "The log file changed during rotation. Refresh and search again.")
                if len(raw) > MAX_LINE_BYTES:
                    raise LogFileError(
                        "too_large",
                        "A log line exceeds the 1 MiB search limit. Narrowing filters cannot read this file.",
                    )
                line = raw.decode("utf-8", errors="replace")
                header = HEADER.match(line)
                if header:
                    finish(position)
                    start = position
                    record_severity = SEVERITIES.get(header[1])
                    parsed_component = _component(header[2])
                    record_component = parsed_component.casefold() if parsed_component else None
                    text_match = not query
                text_match = text_match or query in line.casefold()
                scanned += 1
                position += len(raw)
            finish(position)
            total = sum(end - start for start, end in records)
            while records and total > MAX_RESULT_BYTES:
                if len(records) == 1:
                    raise LogFileError(
                        "too_large", "A matching log record exceeds the 8 MiB result limit. Use a more specific search."
                    )
                start, end = records.popleft()
                total -= end - start
            logs = []
            for start, end in records:
                source.seek(start)
                record = source.read(end - start)
                if len(record) != end - start:
                    raise LogFileError("changed", "The log file changed during rotation. Refresh and search again.")
                logs.extend(
                    redact_sensitive_text(line, provider_secrets)
                    for line in record.decode("utf-8", errors="replace").splitlines(keepends=True)
                )
            _check_unchanged(path, opened)
            return {
                "logs": logs,
                "file": _entry(name, opened),
                "lines_scanned": scanned,
                "records_matched": matched,
                "records_returned": len(records),
                "truncated": matched > len(records),
                "record_limit": limit,
                "byte_limit": MAX_RESULT_BYTES,
            }
    except FileNotFoundError as e:
        raise LogFileError("missing", "The log file no longer exists. Refresh the file list.") from e
    except OSError as e:
        raise LogFileError("unreadable", "Cannot read the selected log file. Check permissions and Refresh.") from e


def download_file(log_dir, selector, provider_secrets=()):
    try:
        name, path, source, opened = _open(log_dir, selector)
    except FileNotFoundError as e:
        raise LogFileError("missing", "The log file no longer exists. Refresh the file list.") from e
    except OSError as e:
        raise LogFileError("unreadable", "Cannot read the selected log file. Check permissions and Refresh.") from e
    return name, _redacted_chunks(path, source, opened, provider_secrets)


def _redacted_chunks(path, source, opened, provider_secrets):
    with source:
        try:
            chunk = []
            size = position = 0
            while position < opened.st_size:
                raw = source.readline(min(MAX_LINE_BYTES + 1, opened.st_size - position))
                if not raw:
                    raise LogFileError("changed", "The log file shrank during the download.")
                if len(raw) > MAX_LINE_BYTES:
                    raise LogFileError("too_large", "A log line exceeds 1 MiB.")
                position += len(raw)
                line = redact_sensitive_text(raw.decode("utf-8", errors="replace"), provider_secrets).encode("utf-8")
                chunk.append(line)
                size += len(line)
                if size >= DOWNLOAD_CHUNK_BYTES:
                    yield b"".join(chunk)
                    chunk = []
                    size = 0
            if chunk:
                yield b"".join(chunk)
            _check_unchanged(path, opened)
        except LogFileError as e:
            yield _incomplete_marker(e.code)
        except OSError:
            yield _incomplete_marker("unreadable")


_INCOMPLETE_REASONS = {
    "changed": "The log file changed or disappeared during the download. Download it again.",
    "too_large": "A log line exceeds 1 MiB and cannot be redacted safely.",
    "unreadable": "Cannot read the selected log file. Check permissions.",
}


def _incomplete_marker(code):
    return f"\n[Comicarr] DOWNLOAD INCOMPLETE: {_INCOMPLETE_REASONS[code]}\n".encode("utf-8")
