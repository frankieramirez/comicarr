#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Prowlarr's Mylar application can sync indexers into Comicarr (#1140).

The requests below are the ones Prowlarr's ``MylarV1Proxy`` builds: a GET to
``/api`` with ``cmd`` and ``apikey`` query parameters, reading Mylar3's JSON
envelope. They run against a real ``Config`` so the save path is the one the
Settings page uses.
"""

import configparser
import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import comicarr
from comicarr.app.core import access_log
from comicarr.app.core.context import AppContext, get_context
from comicarr.app.indexer_sync import service
from comicarr.app.indexer_sync.router import router
from comicarr.app.search.provider_config import providers_from_config
from comicarr.app.search.providers import effective_provider_plan

API_KEY = "a" * 32
PROWLARR_KEY = "prowlarr-own-key"


@pytest.fixture
def config(tmp_path, monkeypatch):
    from comicarr.app.config import ini as config_module
    from comicarr.app.core import encrypted as encrypted_module

    config_path = tmp_path / "config.ini"
    config_path.write_text("")
    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
    monkeypatch.setattr(encrypted_module, "_fernet_instance", None)

    cfg = config_module.Config(str(config_path))
    cfg.config_vals()
    cfg.SECURE_DIR = str(secure_dir)
    config_module.config.set("General", "secure_dir", str(secure_dir))
    cfg.provider_sequence = MagicMock()
    cfg.write_out_provider_searches = MagicMock()
    cfg.API_KEY = API_KEY
    monkeypatch.setattr(comicarr, "CONFIG", cfg)
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    return cfg


@pytest.fixture
def client(config):
    ctx = AppContext(config=config, jwt_secret_key=b"x" * 32, jwt_generation=0)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_context] = lambda: ctx
    return TestClient(app)


def call(client, cmd, apikey=API_KEY, **params):
    response = client.get("/api", params={"cmd": cmd, "apikey": apikey, **params})
    assert response.status_code == 200
    return response.json()


def prowlarr_indexer(indexer_id=3, name="NZBgeek", kind="newznab", **overrides):
    """The parameters ``MylarV1Proxy.AddIndexer`` sends."""
    params = {
        "name": "%s (Prowlarr)" % name,
        "providertype": kind,
        "host": "http://prowlarr:9696/%s/api" % indexer_id,
        "prov_apikey": PROWLARR_KEY,
        "enabled": "true",
        "categories": "7030",
    }
    params.update(overrides)
    return params


class TestAuthentication:
    def test_the_connection_test_succeeds_with_the_api_key(self, client):
        body = call(client, "getVersion")

        assert body["success"] is True
        assert "current_version" in body["data"]

    @pytest.mark.parametrize(
        ("apikey", "message"),
        [("", "Missing API key"), ("wrong", "Incorrect API key")],
    )
    def test_a_bad_key_is_refused_in_a_body_prowlarr_can_show(self, client, apikey, message):
        assert call(client, "listProviders", apikey=apikey) == {
            "success": False,
            "error": {"code": 1, "message": message},
        }

    def test_no_key_configured_refuses_everything(self, client, config):
        config.API_KEY = None

        assert call(client, "getVersion", apikey="anything")["error"]["message"] == "API key not generated"

    def test_other_mylar_commands_are_unknown(self, client):
        assert call(client, "shutdown")["error"]["message"] == "Unknown command: shutdown"


class TestSync:
    def test_an_added_indexer_lands_in_the_normal_provider_list_and_searches(self, client, config):
        config.NEWZNAB = False

        assert call(client, "addProvider", **prowlarr_indexer())["success"] is True

        [record] = providers_from_config(config, "newznab")
        assert (record.name, record.host, record.api_key, record.categories, record.enabled) == (
            "NZBgeek (Prowlarr)",
            "http://prowlarr:9696/3/api",
            PROWLARR_KEY,
            ("7030",),
            True,
        )
        assert record.id is not None
        assert record.verify is False
        assert config.NEWZNAB is True
        plan = effective_provider_plan(config)
        assert "NZBgeek (Prowlarr)" in [candidate.name for candidate in plan]

    def test_a_torznab_indexer_keeps_every_category(self, client, config):
        call(client, "addProvider", **prowlarr_indexer(kind="torznab", name="Nyaa", categories="7030,7020"))

        [record] = providers_from_config(config, "torznab")
        assert record.categories == ("7030", "7020")
        assert providers_from_config(config, "newznab") == []

    def test_list_returns_what_prowlarr_compares(self, client):
        call(client, "addProvider", **prowlarr_indexer())
        call(client, "addProvider", **prowlarr_indexer(indexer_id=4, kind="torznab", name="Nyaa"))

        data = call(client, "listProviders")["data"]

        [newznab] = data["newznabs"]
        [torznab] = data["torznabs"]
        assert {key: newznab[key] for key in ("name", "host", "apikey", "categories", "enabled")} == {
            "name": "NZBgeek (Prowlarr)",
            "host": "http://prowlarr:9696/3/api",
            "apikey": PROWLARR_KEY,
            "categories": "7030",
            "enabled": True,
        }
        assert torznab["name"] == "Nyaa (Prowlarr)"

    def test_list_never_returns_a_key_prowlarr_did_not_write(self, client, config):
        config.EXTRA_NEWZNABS = [("My indexer", "https://indexer.test/api", "1", "private-key", "1#7030", "1", 50)]

        [row] = call(client, "listProviders")["data"]["newznabs"]

        assert row["apikey"] == ""
        assert row["name"] == "My indexer"

    def test_change_renames_and_updates_the_indexer_prowlarr_names(self, client, config):
        call(client, "addProvider", **prowlarr_indexer())
        [before] = providers_from_config(config, "newznab")

        body = call(
            client,
            "changeProvider",
            **prowlarr_indexer(altername="Geek (Prowlarr)", enabled="false", categories="7030,7020"),
        )

        assert body["success"] is True
        [after] = providers_from_config(config, "newznab")
        assert (after.name, after.enabled, after.categories, after.id) == (
            "Geek (Prowlarr)",
            False,
            ("7030", "7020"),
            before.id,
        )

    def test_delete_removes_only_the_named_indexer(self, client, config):
        config.EXTRA_NEWZNABS = [("My indexer", "https://indexer.test/api", "1", "private-key", "1#7030", "1", 50)]
        call(client, "addProvider", **prowlarr_indexer())

        body = call(client, "delProvider", name="NZBgeek (Prowlarr)", providertype="newznab")

        assert body["success"] is True
        [kept] = providers_from_config(config, "newznab")
        assert (kept.name, kept.api_key) == ("My indexer", "private-key")

    def test_the_last_indexer_can_be_deleted(self, client, config):
        call(client, "addProvider", **prowlarr_indexer(kind="torznab"))

        assert call(client, "delProvider", name="NZBgeek (Prowlarr)", providertype="torznab")["success"] is True
        assert providers_from_config(config, "torznab") == []

    def test_a_reset_prowlarr_re_adding_its_indexer_updates_it(self, client, config):
        call(client, "addProvider", **prowlarr_indexer())

        body = call(client, "addProvider", **prowlarr_indexer(host="http://prowlarr:9696/9/api"))

        assert body["success"] is True
        [record] = providers_from_config(config, "newznab")
        assert record.host == "http://prowlarr:9696/9/api"

    def test_an_operator_indexer_with_the_same_name_is_not_overwritten(self, client, config):
        config.EXTRA_NEWZNABS = [
            ("NZBgeek (Prowlarr)", "https://api.nzbgeek.info", "1", "private-key", "1#7030", "1", 50)
        ]

        body = call(client, "addProvider", **prowlarr_indexer())

        assert body["success"] is False
        assert "already exists" in body["error"]["message"]
        [record] = providers_from_config(config, "newznab")
        assert record.api_key == "private-key"


class TestRefusals:
    @pytest.mark.parametrize(
        ("cmd", "params", "message"),
        [
            ("addProvider", {"providertype": "nzb"}, "not a valid option"),
            ("addProvider", {"providertype": "newznab", "name": "x"}, "Missing argument"),
            ("addProvider", prowlarr_indexer(host="prowlarr:9696/3/api"), "http://"),
            ("addProvider", prowlarr_indexer(enabled="maybe"), "`enabled`"),
            ("changeProvider", prowlarr_indexer(), "does not exist"),
            ("delProvider", {"providertype": "torznab", "name": "nope"}, "does not exist"),
            ("delProvider", {"name": "nope"}, "No provider type"),
        ],
    )
    def test_bad_requests_are_explained(self, client, cmd, params, message):
        body = call(client, cmd, **params)

        assert body["success"] is False
        assert message in body["error"]["message"]

    def test_the_prowlarr_search_name_stays_reserved(self, client, config):
        config.ENABLE_PROWLARR = True
        config.PROWLARR_HOST = "http://prowlarr:9696"
        config.PROWLARR_APIKEY = "key"

        body = call(client, "addProvider", **{**prowlarr_indexer(), "name": "Prowlarr"})

        assert body["success"] is False
        assert providers_from_config(config, "newznab") == []


def test_access_log_redacts_both_keys():
    record = logging.LogRecord(
        access_log.ACCESS_LOGGER,
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api?cmd=addProvider&apikey=secret1&prov_apikey=secret2&name=x", "1.1", 200),
        None,
    )

    access_log.QueryKeyRedactionFilter().filter(record)

    message = record.getMessage()
    assert "secret1" not in message and "secret2" not in message
    assert "name=x" in message


def test_service_never_raises_on_an_unexpected_error(monkeypatch, config):
    ctx = AppContext(config=config, jwt_secret_key=b"x" * 32, jwt_generation=0)
    monkeypatch.setattr(service, "providers_from_config", MagicMock(side_effect=RuntimeError("boom")))

    body = service.handle(ctx, {"cmd": "listProviders", "apikey": API_KEY})

    assert body["success"] is False
    assert "boom" not in body["error"]["message"]


def test_a_synced_indexer_is_written_to_config_ini_with_its_key_encrypted(client, config, tmp_path):
    call(client, "addProvider", **prowlarr_indexer())

    stored = (tmp_path / "config.ini").read_text()

    assert "NZBgeek (Prowlarr)" in stored
    assert PROWLARR_KEY not in stored
