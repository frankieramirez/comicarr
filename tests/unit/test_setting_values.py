#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""A settings save stores what was typed or says why it can't (#1492)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comicarr.app.config.ini import SCHEDULER_INTERVAL_MINIMUMS, SEARCH_DELAY_FLOOR_SECONDS
from comicarr.app.config.registry import REGISTRY
from comicarr.app.config.setting_values import check_setting_values
from comicarr.app.system import service as system_service

MINIMUM_KEYS = sorted(name for name, key in REGISTRY.items() if key.minimum is not None)


def _ctx(**config):
    cfg = MagicMock()
    cfg.DISCORD_ENABLED = False
    cfg.DISCORD_WEBHOOK_URL = None
    for name, value in config.items():
        setattr(cfg, name, value)
    cfg.apply_transaction.return_value = True
    return SimpleNamespace(config=cfg, scheduler=None)


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    import comicarr

    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.setattr(system_service, "_reconfigure_schedulers", lambda _ctx: None)
    monkeypatch.setattr(system_service, "recheck_connections", lambda _ctx: None)


class TestMinimums:
    @pytest.mark.parametrize("name", MINIMUM_KEYS)
    @pytest.mark.parametrize("offset", [1, 6])
    def test_a_value_below_the_minimum_is_refused_not_raised(self, name, offset):
        ctx = _ctx()
        minimum = REGISTRY[name].minimum
        result = system_service.update_config(ctx, {name.lower(): minimum - offset})

        assert result["success"] is False
        assert result["code"] == "setting_below_minimum"
        assert result["field"] == name.lower()
        assert result["params"] == {"minimum": minimum}
        ctx.config.apply_transaction.assert_not_called()

    def test_the_reported_case_is_refused(self):
        ctx = _ctx()
        result = system_service.update_config(ctx, {"search_interval": -5})

        assert result["code"] == "setting_below_minimum"
        assert result["params"] == {"minimum": 360}

    @pytest.mark.parametrize("name", MINIMUM_KEYS)
    def test_the_minimum_itself_is_stored_as_typed(self, name):
        ctx = _ctx()
        minimum = REGISTRY[name].minimum
        result = system_service.update_config(ctx, {name.lower(): minimum})

        assert result == {"success": True}
        ctx.config.apply_transaction.assert_called_once_with({name: minimum})

    @pytest.mark.parametrize("value", ["soon", True, None, "1.5"])
    def test_a_value_that_is_not_a_whole_number_is_refused(self, value):
        result = check_setting_values(_ctx().config, {"SEARCH_INTERVAL": value})

        assert result["code"] == "setting_not_whole_number"
        assert result["field"] == "search_interval"

    def test_ini_loading_uses_the_same_floors(self):
        for name, (minimum, _message) in SCHEDULER_INTERVAL_MINIMUMS.items():
            assert REGISTRY[name].minimum == minimum
        assert REGISTRY["SEARCH_DELAY"].minimum == SEARCH_DELAY_FLOOR_SECONDS


class TestMangaDexLists:
    def test_unknown_language_codes_are_named(self):
        result = check_setting_values(_ctx().config, {"MANGADEX_LANGUAGES": "en, english, j"})

        assert result["code"] == "mangadex_language_unknown"
        assert result["params"] == {"codes": "english, j"}

    def test_valid_codes_are_kept_and_tidied(self):
        filtered = {"MANGADEX_LANGUAGES": " EN, pt-BR ,en,ja-ro"}
        assert check_setting_values(_ctx().config, filtered) is None
        assert filtered["MANGADEX_LANGUAGES"] == "en,pt-br,ja-ro"

    def test_an_empty_list_still_means_the_default(self):
        filtered = {"MANGADEX_LANGUAGES": "", "MANGADEX_CONTENT_RATING": ""}
        assert check_setting_values(_ctx().config, filtered) is None
        assert filtered == {"MANGADEX_LANGUAGES": "", "MANGADEX_CONTENT_RATING": ""}

    def test_unknown_content_ratings_are_named(self):
        result = check_setting_values(_ctx().config, {"MANGADEX_CONTENT_RATING": "safe,spicy"})

        assert result["code"] == "mangadex_rating_unknown"
        assert result["params"] == {"ratings": "spicy"}


class TestDiscord:
    def test_turning_on_without_a_webhook_is_refused(self):
        result = check_setting_values(_ctx().config, {"DISCORD_ENABLED": True})

        assert result["code"] == "discord_webhook_required"
        assert result["field"] == "discord_webhook_url"

    def test_turning_on_with_a_webhook_in_the_same_save_works(self):
        filtered = {"DISCORD_ENABLED": True, "DISCORD_WEBHOOK_URL": "https://discord.example/api/webhooks/1/x"}
        assert check_setting_values(_ctx().config, filtered) is None

    def test_turning_on_with_a_stored_webhook_works(self):
        config = _ctx(DISCORD_WEBHOOK_URL="https://discord.example/api/webhooks/1/x").config
        assert check_setting_values(config, {"DISCORD_ENABLED": True}) is None

    def test_clearing_the_webhook_while_on_is_refused(self):
        config = _ctx(DISCORD_ENABLED=True, DISCORD_WEBHOOK_URL="https://discord.example/api/webhooks/1/x").config
        result = check_setting_values(config, {"DISCORD_WEBHOOK_URL": "  "})

        assert result["code"] == "discord_webhook_required"

    def test_turning_off_needs_no_webhook(self):
        assert check_setting_values(_ctx().config, {"DISCORD_ENABLED": False}) is None
