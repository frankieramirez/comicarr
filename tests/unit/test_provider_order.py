#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Global Search provider order set from Settings (#1117)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from comicarr.app.search.providers import effective_provider_plan, ordered_provider_names
from comicarr.app.system import service as system_service
from tests.unit.test_system_domain import _make_real_config, _make_test_ctx


def _newznab(name, provider_id, enabled="1"):
    return (name, "https://%s.test" % name.lower().replace(" ", ""), "1", "key-%s" % provider_id, "1#7030", enabled, provider_id)


def _config(**overrides):
    values = {
        "ENABLE_DDL": False,
        "EXPERIMENTAL": False,
        "NEWZNAB": True,
        "EXTRA_NEWZNABS": [_newznab("NZBgeek", 11), _newznab("NZB", 12), _newznab("DrunkenSlug", 13)],
        "ENABLE_TORRENT_SEARCH": False,
        "PROVIDER_ORDER": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _names(config):
    return [candidate.name for candidate in effective_provider_plan(config)]


def test_more_than_ten_providers_are_searched_in_numeric_order():
    names = ["Indexer %02d" % index for index in range(12)]
    config = _config(
        EXTRA_NEWZNABS=[_newznab(name, 100 + index) for index, name in enumerate(names)],
        PROVIDER_ORDER={str(index): name for index, name in enumerate(names)},
    )

    assert ordered_provider_names(config) == names
    assert _names(config) == names


def test_the_ini_form_of_the_order_is_read_too():
    assert ordered_provider_names(SimpleNamespace(PROVIDER_ORDER="0, B, 1, A, 10, C, 2, D")) == ["B", "A", "D", "C"]


def test_an_exact_name_wins_over_a_partial_one():
    config = _config(PROVIDER_ORDER={"0": "NZB", "1": "DrunkenSlug", "2": "NZBgeek"})

    assert _names(config) == ["NZB", "DrunkenSlug", "NZBgeek"]


def test_an_indexer_missing_from_the_saved_order_goes_last():
    config = _config(PROVIDER_ORDER={"0": "DrunkenSlug", "1": "NZB"})

    assert _names(config) == ["DrunkenSlug", "NZB", "NZBgeek"]


def test_a_series_override_still_beats_the_global_order():
    config = _config(PROVIDER_ORDER={"0": "DrunkenSlug", "1": "NZB", "2": "NZBgeek"})

    plan = effective_provider_plan(config, override={"order": ["NZBgeek"]})

    assert [candidate.name for candidate in plan] == ["NZBgeek", "DrunkenSlug", "NZB"]


def _ctx(config):
    ctx = _make_test_ctx()
    ctx.config = config
    return ctx


def test_get_lists_providers_in_search_order_without_secrets():
    config = _config(PROVIDER_ORDER={"0": "DrunkenSlug", "1": "NZB", "2": "NZBgeek"})

    result = system_service.get_provider_order(_ctx(config))

    assert result == {
        "providers": [
            {"name": "DrunkenSlug", "kind": "newznab", "route": "nzb"},
            {"name": "NZB", "kind": "newznab", "route": "nzb"},
            {"name": "NZBgeek", "kind": "newznab", "route": "nzb"},
        ]
    }
    assert "key-" not in str(result)
    assert ".test" not in str(result)


def test_saving_writes_the_canonical_names_in_the_new_order():
    config = _config()
    saved = []

    def save(names):
        saved.append(names)
        config.PROVIDER_ORDER = {str(index): name for index, name in enumerate(names)}
        return True

    config.save_provider_order = save

    result = system_service.update_provider_order(_ctx(config), {"order": ["drunkenslug", "NZBgeek", "nzb"]})

    assert saved == [["DrunkenSlug", "NZBgeek", "NZB"]]
    assert result["success"] is True
    assert [row["name"] for row in result["providers"]] == ["DrunkenSlug", "NZBgeek", "NZB"]


@pytest.mark.parametrize(
    "body",
    [
        {"order": ["NZBgeek", "NZB"]},
        {"order": ["NZBgeek", "NZB", "DrunkenSlug", "Unknown"]},
        {"order": ["NZBgeek", "NZB", "NZB"]},
        {"order": "NZBgeek, NZB, DrunkenSlug"},
        {"order": [1, 2, 3]},
        None,
    ],
)
def test_an_order_that_is_not_every_enabled_provider_once_is_refused(body):
    config = _config()
    config.save_provider_order = MagicMock()

    result = system_service.update_provider_order(_ctx(config), body)

    assert result["success"] is False
    config.save_provider_order.assert_not_called()


def test_a_name_with_a_comma_cannot_be_saved_in_the_order():
    config = _config(EXTRA_NEWZNABS=[_newznab("Slug, Inc", 11), _newznab("NZB", 12)])
    config.save_provider_order = MagicMock()

    result = system_service.update_provider_order(_ctx(config), {"order": ["NZB", "Slug, Inc"]})

    assert result == {
        "success": False,
        "error": 'Rename "Slug, Inc" under Search first: a provider name in the order cannot contain a comma',
    }
    config.save_provider_order.assert_not_called()


def test_a_failed_write_is_reported_as_a_persistence_error():
    config = _config()
    config.save_provider_order = MagicMock(return_value=False)

    result = system_service.update_provider_order(_ctx(config), {"order": ["NZB", "NZBgeek", "DrunkenSlug"]})

    assert result == {"success": False, "error": system_service.PROVIDER_CONFIG_PERSISTENCE_ERROR}


def test_the_saved_order_round_trips_through_config_ini(tmp_path, monkeypatch):
    cfg, config_path, config_module = _make_real_config(tmp_path, monkeypatch)
    names = ["Indexer %02d" % index for index in range(11)]

    assert cfg.save_provider_order(list(reversed(names))) is True

    text = config_path.read_text()
    assert "provider_order = 0, Indexer 10, 1, Indexer 09" in text
    cfg.provider_sequence.assert_called_once_with()

    reloaded = configparser_order(config_path)
    assert ordered_provider_names(SimpleNamespace(PROVIDER_ORDER=reloaded)) == list(reversed(names))


def configparser_order(path):
    import configparser

    parser = configparser.ConfigParser()
    parser.read(path)
    return parser.get("Providers", "provider_order")


def test_reconciling_the_saved_order_keeps_it_and_appends_new_indexers(tmp_path, monkeypatch):
    cfg, _config_path, _module = _make_real_config(tmp_path, monkeypatch)
    cfg.NEWZNAB = True
    cfg.EXTRA_NEWZNABS = [_newznab("NZBgeek", 11), _newznab("NZB", 12), _newznab("DrunkenSlug", 13)]
    cfg.PROVIDER_ORDER = "0, DrunkenSlug, 1, NZBgeek, 2, NZB"

    order, _serialized = cfg._calculate_provider_order()
    assert ordered_provider_names(SimpleNamespace(PROVIDER_ORDER=order)) == ["DrunkenSlug", "NZBgeek", "NZB"]

    cfg.PROVIDER_ORDER = order
    cfg.EXTRA_NEWZNABS = cfg.EXTRA_NEWZNABS + [_newznab("Newcomer", 14)]
    order, _serialized = cfg._calculate_provider_order()
    assert ordered_provider_names(SimpleNamespace(PROVIDER_ORDER=order)) == ["DrunkenSlug", "NZBgeek", "NZB", "Newcomer"]


def test_a_failed_reconcile_puts_the_previous_order_back(tmp_path, monkeypatch):
    cfg, config_path, _module = _make_real_config(tmp_path, monkeypatch)
    cfg.PROVIDER_ORDER = {"0": "NZBgeek", "1": "NZB"}
    cfg.provider_sequence = MagicMock(side_effect=[RuntimeError("database locked"), None])

    with pytest.raises(RuntimeError):
        cfg.save_provider_order(["NZB", "NZBgeek"])

    assert "provider_order = 0, NZBgeek, 1, NZB" in config_path.read_text()
    assert cfg.provider_sequence.call_count == 2
