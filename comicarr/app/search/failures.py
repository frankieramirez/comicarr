#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Plain-language provider failures and the shared unreachable-host memo.

A search sends one request per provider per query variant.  When several
providers sit behind one host (every indexer Prowlarr syncs lives at the
Prowlarr address), a refused connection on the first request says the same
thing about all of them.  :func:`mark_unreachable` remembers that host for a
short window so the rest of the search fails without another socket, and
:func:`describe` turns a ``requests`` exception into the sentence the
Review releases dialog shows.  The raw exception stays in the log.
"""

from __future__ import annotations

import errno
import socket
import threading
import time
from urllib.parse import urlsplit

import requests

UNREACHABLE_TTL_SECONDS = 120

_lock = threading.Lock()
_unreachable: dict[str, tuple[float, str, str]] = {}


def host_label(url) -> str:
    """Return ``host:port`` for a URL, without its path, query or credentials."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return ""
    host = parts.hostname or ""
    if not host:
        return ""
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None:
        port = 443 if parts.scheme == "https" else 80 if parts.scheme == "http" else None
    return "%s:%s" % (host, port) if port else host


def _errnos(exc, depth=0):
    if exc is None or depth > 6:
        return
    code = getattr(exc, "errno", None)
    if isinstance(code, int) and code:
        yield code, exc
    for nested in list(getattr(exc, "args", ()) or ()) + [exc.__cause__, exc.__context__]:
        if isinstance(nested, BaseException):
            yield from _errnos(nested, depth + 1)


def _cause(exc) -> str:
    for code, nested in _errnos(exc):
        if isinstance(nested, socket.gaierror) or code in {
            getattr(socket, "EAI_NONAME", -2),
            getattr(socket, "EAI_AGAIN", -3),
            getattr(socket, "EAI_FAIL", -4),
        }:
            return "dns"
        if code == errno.ECONNREFUSED:
            return "refused"
        if code in {errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN, errno.ENETDOWN}:
            return "unreachable"
        if code == errno.ECONNRESET:
            return "reset"
        if code == errno.ETIMEDOUT:
            return "timeout"
    if isinstance(exc, requests.exceptions.SSLError):
        return "ssl"
    if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout)):
        return "timeout"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"
    text = str(exc).lower()
    if "name or service not known" in text or "nodename nor servname" in text or "failed to resolve" in text:
        return "dns"
    if "connection refused" in text:
        return "refused"
    return "other"


def describe(exc, url, *, timeout=None) -> str:
    """Return one sentence a person can act on for a failed provider request."""
    host = host_label(url) or "the provider"
    cause = _cause(exc)
    if cause == "refused":
        return (
            "Couldn't connect to %s: nothing accepted the connection. Check that the service is running "
            "and listening on that port, and that Comicarr can reach it." % host
        )
    if cause == "dns":
        return (
            "Couldn't find a host named %s. Check the address in the provider settings, or that both "
            "containers share a Docker network." % host.rsplit(":", 1)[0]
        )
    if cause == "unreachable":
        return "Couldn't reach %s: the network has no route to it." % host
    if cause == "reset":
        return "%s closed the connection before answering." % host
    if cause == "timeout":
        if timeout:
            return "%s didn't answer within %s seconds." % (host, int(timeout))
        return "%s didn't answer in time." % host
    if cause == "ssl":
        return "Couldn't set up a secure connection to %s. Check its certificate or use http." % host
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status in (401, 403):
        return "%s refused the request (HTTP %s). Check the API key." % (host, status)
    if status:
        return "%s answered with HTTP %s." % (host, status)
    return "The request to %s failed." % host


def mark_unreachable(url, code: str, message: str) -> None:
    """Remember that ``url``'s host refused or could not be reached."""
    host = host_label(url)
    if not host:
        return
    with _lock:
        _unreachable[host] = (time.monotonic() + UNREACHABLE_TTL_SECONDS, code, message)


def unreachable(url) -> tuple[str, str] | None:
    """Return ``(code, message)`` while ``url``'s host is remembered as unreachable."""
    host = host_label(url)
    if not host:
        return None
    with _lock:
        entry = _unreachable.get(host)
        if entry is None:
            return None
        expires, code, message = entry
        if time.monotonic() >= expires:
            _unreachable.pop(host, None)
            return None
        return code, message


def clear() -> None:
    """Forget every remembered host."""
    with _lock:
        _unreachable.clear()
