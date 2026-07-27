#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Cloudflare origin errors from the pull-list host are a known condition.

Cloudflare answers on the origin's behalf when it is unhealthy, so these
arrive as ordinary responses. Left unclassified they fell through to the
catch-all branch, which logged the entire response header dict — the
observed noise was a 523 spilling ~10 headers into one WARNING line.
"""

from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr import locg


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.setattr(comicarr, "USER_AGENT", "Comicarr/1.0.0 (comicarr)")
    monkeypatch.setattr(comicarr, "BACKENDSTATUS_WS", "up", raising=False)
    warnings = []
    monkeypatch.setattr(locg.logger, "warn", lambda message: warnings.append(message))

    def respond(status_code, headers=None):
        response = MagicMock()
        response.status_code = status_code
        response.headers = headers or {}
        monkeypatch.setattr(locg.requests, "get", MagicMock(return_value=response))
        return locg.locg(weeknumber="30", year="2026")

    respond.warnings = warnings
    return respond


@pytest.mark.parametrize("status_code", sorted(locg.CLOUDFLARE_ORIGIN_ERRORS))
def test_origin_errors_are_reported_as_a_transient_outage(upstream, status_code):
    result = upstream(int(status_code))

    assert result == {"status": "failure"}
    assert comicarr.BACKENDSTATUS_WS == "down"

    message = upstream.warnings[-1]
    assert status_code in message
    assert "stale" in message


def test_the_523_that_was_observed_no_longer_dumps_response_headers(upstream):
    """The regression: every header landed in the log line verbatim."""
    upstream(523, headers={"Server": "cloudflare", "CF-RAY": "a213a6096a125f15-EWR", "Expires": "Thu, 01 Jan 1970"})

    message = upstream.warnings[-1]
    assert "CF-RAY" not in message
    assert "cloudflare" not in message
    assert "unreachable" in message


def test_retry_after_is_surfaced_when_upstream_supplies_one(upstream):
    upstream(523, headers={"Retry-After": "120"})

    assert "retry in 120 seconds" in upstream.warnings[-1]


def test_date_form_retry_after_is_not_reported_as_seconds(upstream):
    """RFC 9110 allows an HTTP date here, which is not a delay in seconds."""
    upstream(523, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})

    message = upstream.warnings[-1]
    assert "retry after Wed, 21 Oct 2026 07:28:00 GMT" in message
    assert "seconds" not in message


def test_no_retry_advice_is_invented_when_upstream_omits_it(upstream):
    upstream(522)

    assert "retry in" not in upstream.warnings[-1]


def test_unrecognised_status_codes_still_reach_the_diagnostic_branch(upstream):
    """525 is a Cloudflare SSL error, not an origin-health one: keep the headers."""
    result = upstream(525, headers={"CF-RAY": "abc123"})

    assert result == {"status": "failure"}
    assert "CF-RAY" in upstream.warnings[-1]
