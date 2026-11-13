#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The deprecation registry, its startup warning and its system route (ADR-0006)."""

import pytest

from comicarr.app.system import deprecations
from comicarr.app.system import router as system_router


def _entry(in_use):
    return deprecations.Deprecation(
        id="fake-feature",
        name="Fake feature",
        announced_in="0.52.0",
        removable_from="1.0.0",
        replacement="Real feature",
        docs_url="https://comicarr.com/docs/deprecations#fake-feature",
        in_use=in_use,
    )


@pytest.fixture
def logged(monkeypatch):
    lines = {"warn": [], "error": []}
    monkeypatch.setattr(deprecations.logger, "warn", lambda message: lines["warn"].append(message))
    monkeypatch.setattr(deprecations.logger, "error", lambda message: lines["error"].append(message))
    return lines


def _register(monkeypatch, *entries):
    monkeypatch.setattr(deprecations, "REGISTRY", list(entries))


def _boom():
    raise RuntimeError("database is locked")


def test_the_registry_ships_empty():
    assert deprecations.REGISTRY == []


def test_an_entry_in_use_is_returned_and_warned_about_once(monkeypatch, logged):
    _register(monkeypatch, _entry(lambda: True))

    deprecations.warn_deprecations_in_use()

    assert system_router.get_deprecations() == {
        "deprecations": [
            {
                "id": "fake-feature",
                "name": "Fake feature",
                "announced_in": "0.52.0",
                "removable_from": "1.0.0",
                "replacement": "Real feature",
                "docs_url": "https://comicarr.com/docs/deprecations#fake-feature",
            }
        ]
    }
    assert len(logged["warn"]) == 1
    assert "Fake feature" in logged["warn"][0]


def test_an_entry_not_in_use_is_silent(monkeypatch, logged):
    _register(monkeypatch, _entry(lambda: False))

    deprecations.warn_deprecations_in_use()

    assert system_router.get_deprecations() == {"deprecations": []}
    assert logged == {"warn": [], "error": []}


def test_a_predicate_that_raises_counts_as_not_in_use(monkeypatch, logged):
    _register(monkeypatch, _entry(_boom), _entry(lambda: True))

    deprecations.warn_deprecations_in_use()

    assert [entry.id for entry in deprecations.deprecations_in_use()] == ["fake-feature"]
    assert len(logged["warn"]) == 1
    assert "database is locked" in logged["error"][0]
