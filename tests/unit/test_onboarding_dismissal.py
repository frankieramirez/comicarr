#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Finishing onboarding must persist, or the dialog returns on every load.

The onboarding dialog opens while the database is empty and
``MIGRATION_DISMISSED`` is false, and closing it saves the flag through
``PUT /api/config``. The registry never marked the key writable, so
``update_config`` rejected the whole payload with "No valid config keys
provided" and the frontend only logged a warning. The e2e harness seeds the
flag straight into config.ini, which is why nothing caught it.
"""

import pytest

import comicarr
from comicarr.app.config.registry import REGISTRY, readable_keys, writable_keys
from comicarr.app.core.context import AppContext
from comicarr.app.system import service as system_service


class FakeConfig:
    """Records what update_config persists, the way Config.apply_transaction would."""

    def __init__(self):
        self.MIGRATION_DISMISSED = False
        self.transactions = []

    def apply_transaction(self, values, configure=True):
        self.transactions.append(dict(values))
        for key, value in values.items():
            setattr(self, key.upper(), value)
        return True


@pytest.fixture
def ctx(monkeypatch):
    config = FakeConfig()
    monkeypatch.setattr(comicarr, "CONFIG", config, raising=False)
    return AppContext(config=config)


def test_migration_dismissed_is_writable_but_not_a_settings_field():
    key = REGISTRY["MIGRATION_DISMISSED"]
    assert key.writable is True
    assert "MIGRATION_DISMISSED" in writable_keys()
    # The flag reaches the frontend through the diagnostics payload, not the
    # Settings form, so it stays off GET /api/config.
    assert key.readable is False
    assert "MIGRATION_DISMISSED" not in readable_keys()


@pytest.mark.parametrize(
    "payload",
    [
        {"migration_dismissed": True},  # what the frontend sends
        {"MIGRATION_DISMISSED": "true"},  # what earlier frontends sent
    ],
)
def test_dismissing_onboarding_is_saved(ctx, payload):
    result = system_service.update_config(ctx, payload)

    assert result == {"success": True}
    assert ctx.config.transactions == [{"MIGRATION_DISMISSED": next(iter(payload.values()))}]
