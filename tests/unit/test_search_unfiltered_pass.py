#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from comicarr import search


def test_unfiltered_pass_inactive_by_default():
    assert search.unfiltered_pass_active() is False


def test_unfiltered_pass_scopes_to_the_context_manager():
    with search.unfiltered_series_pass():
        assert search.unfiltered_pass_active() is True
    assert search.unfiltered_pass_active() is False


def test_unfiltered_pass_resets_after_an_exception():
    try:
        with search.unfiltered_series_pass():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert search.unfiltered_pass_active() is False


def test_bare_pass_stays_torznab_only_outside_the_unfiltered_pass():
    assert search._bare_pack_pass_allowed({"type": "torznab", "id": 1}) is True
    assert search._bare_pack_pass_allowed({"type": "newznab", "id": 1}) is False


def test_unfiltered_pass_extends_the_bare_pass_to_newznab():
    with search.unfiltered_series_pass():
        assert search._bare_pack_pass_allowed({"type": "torznab", "id": 1}) is True
        assert search._bare_pack_pass_allowed({"type": "newznab", "id": 1}) is True
        # Non-indexer providers have no bare-query seam even unfiltered.
        assert search._bare_pack_pass_allowed({"type": "DDL"}) is False
        assert search._bare_pack_pass_allowed({"type": "experimental"}) is False
        assert search._bare_pack_pass_allowed({"type": "torrent"}) is False
        assert search._bare_pack_pass_allowed("experimental") is False


def _adapter_retries(session, prefix="https://"):
    return session.get_adapter(prefix + "example.test").max_retries.total


def test_http_session_retries_by_default():
    assert _adapter_retries(search.get_http_session()) == 3


def test_unfiltered_pass_uses_a_no_retry_session():
    # One query per indexer, no retries (#767): a failing indexer surfaces
    # its error instead of being retried by the transport layer.
    with search.unfiltered_series_pass():
        session = search.get_http_session()
    assert _adapter_retries(session) == 0
    assert _adapter_retries(session, "http://") == 0
    # The shared retrying session is untouched.
    assert _adapter_retries(search.get_http_session()) == 3
