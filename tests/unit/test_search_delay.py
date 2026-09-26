#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import types

import comicarr
from comicarr import search
from comicarr.config import clamp_search_delay, minutes_to_search_delay_seconds


def test_configured_search_delay_is_seconds(monkeypatch):
    monkeypatch.setattr(
        comicarr,
        "CONFIG",
        types.SimpleNamespace(SEARCH_DELAY=10),
        raising=False,
    )

    assert search.check_the_search_delay() == 10


def test_search_delay_below_five_seconds_is_raised():
    cfg = types.SimpleNamespace(SEARCH_DELAY=2)

    assert clamp_search_delay(cfg) is True
    assert cfg.SEARCH_DELAY == 5


def test_a_stored_zero_minutes_becomes_the_old_one_minute_wait():
    assert minutes_to_search_delay_seconds("0") == 60
    assert minutes_to_search_delay_seconds(4) == 240


def test_search_delay_at_or_above_the_floor_is_kept():
    cfg = types.SimpleNamespace(SEARCH_DELAY=60)

    assert clamp_search_delay(cfg) is False
    assert cfg.SEARCH_DELAY == 60
