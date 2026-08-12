#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""CONFIG_VERSION migrations: 15 → 16 → 17 → 18."""

import configparser
from pathlib import Path
from unittest.mock import MagicMock

import comicarr
from comicarr import config as config_module
from comicarr.app.config.registry import REGISTRY


def _load_config(tmp_path, monkeypatch, body: str):
    """Load a Config the way neighboring config-transaction tests do."""
    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ini = data_dir / "config.ini"
    # Inject secure_dir so encryption authority setup is a no-op for plaintext.
    if "secure_dir" not in body.lower():
        body = body.replace("[General]", "[General]\nsecure_dir = %s" % secure_dir, 1)
    ini.write_text(body, encoding="utf-8")

    monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
    monkeypatch.setattr(comicarr, "DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(comicarr, "PROG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)

    cfg = config_module.Config(str(ini))
    cfg.configure = MagicMock()
    cfg.provider_sequence = MagicMock()
    monkeypatch.setattr(
        "comicarr.maintenance.Maintenance.backup_files",
        lambda self, **kwargs: True,
        raising=False,
    )
    return cfg, ini


def test_migration_flips_check_github_false_to_true(tmp_path, monkeypatch):
    cfg, ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 15
minimal_ini = False
auto_update = True
encrypt_passwords = False

[Git]
check_github = False
check_github_on_startup = True
""",
    )

    assert cfg.read(startup=False) is cfg

    assert cfg.CONFIG_VERSION == 18
    assert cfg.CHECK_GITHUB is True
    assert REGISTRY["CHECK_GITHUB"].default is True
    assert REGISTRY["CONFIG_VERSION"].default == 18
    assert "AUTO_UPDATE" not in REGISTRY
    assert "CHECK_GITHUB_ON_STARTUP" not in REGISTRY

    text = ini.read_text(encoding="utf-8").lower()
    assert "auto_update" not in text
    assert "check_github_on_startup" not in text
    assert "check_github" in text


def test_migration_does_not_reflip_after_version_16(tmp_path, monkeypatch):
    """Once past 16, an explicit operator opt-out must stick."""
    cfg, _ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 16
minimal_ini = False
encrypt_passwords = False

[Git]
check_github = False
""",
    )

    assert cfg.read(startup=False) is cfg

    assert cfg.CONFIG_VERSION == 18
    assert cfg.CHECK_GITHUB is False


def test_migration_scrubs_host_return_from_the_ini(tmp_path, monkeypatch):
    """16 → 17: host_return has no consumer once SAB uploads the nzb directly.

    Leaving the key would present an operator with a setting that silently
    does nothing, so it is hard-deleted from config.ini rather than ignored
    (ADR-0002 / #552 / #564).
    """
    cfg, ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 16
minimal_ini = False
encrypt_passwords = False

[Interface]
http_port = 8090
host_return = http://comicarr.example:8090/
""",
    )

    assert cfg.read(startup=False) is cfg

    assert cfg.CONFIG_VERSION == 18
    assert "HOST_RETURN" not in REGISTRY
    assert not hasattr(cfg, "HOST_RETURN")

    text = ini.read_text(encoding="utf-8").lower()
    assert "host_return" not in text
    # Neighbouring keys in the same section survive the scrub.
    assert "http_port" in text


def test_migration_removes_legacy_folder_scan_verbosity(tmp_path, monkeypatch):
    """17 → 18 removes the hidden scan switch and explains the new policy once."""
    cfg, ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 17
minimal_ini = False
folder_scan_log_verbose = True
""",
    )
    info = MagicMock()
    monkeypatch.setattr(config_module.logger, "info", info)

    assert cfg.read(startup=False) is cfg

    assert cfg.CONFIG_VERSION == 18
    assert REGISTRY["CONFIG_VERSION"].default == 18
    assert "FOLDER_SCAN_LOG_VERBOSE" not in REGISTRY
    assert not hasattr(cfg, "FOLDER_SCAN_LOG_VERBOSE")
    assert "folder_scan_log_verbose" not in ini.read_text(encoding="utf-8").lower()
    info.assert_any_call(
        "[CONFIG] Removed folder_scan_log_verbose: folder-scan diagnostics now follow LOG_LEVEL=debug."
    )


def test_legacy_torznab_fields_absorbed_on_modern_config(tmp_path, monkeypatch):
    """#631: torznab_* single-provider fields repopulated on a modern config are
    folded into extra_torznabs instead of sitting silently inert."""
    cfg, ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 18
minimal_ini = False
encrypt_passwords = False

[Torznab]
enable_torznab = True
torznab_name = Nyaa
torznab_host = http://prowlarr.example:9696/1/api
torznab_apikey = abc123
torznab_category = 8020
""",
    )

    assert cfg.read(startup=False) is cfg

    hosts = [entry[1] for entry in cfg.EXTRA_TORZNABS]
    assert "http://prowlarr.example:9696/1/api" in hosts
    migrated = cfg.EXTRA_TORZNABS[hosts.index("http://prowlarr.example:9696/1/api")]
    assert migrated[0] == "Nyaa"
    assert migrated[3] == "abc123"
    assert migrated[4] == "8020"
    assert migrated[5] == "1"

    assert cfg.TORZNAB_NAME is None
    assert cfg.TORZNAB_HOST is None
    text = ini.read_text(encoding="utf-8").lower()
    assert "torznab_host" not in text
    assert "extra_torznabs" in text


def test_legacy_torznab_migration_skips_reserved_provider_ids(tmp_path, monkeypatch):
    """The migrated entry must not claim an id held by a built-in provider
    (experimental=101, DDL=200/201) or provider validation rejects it."""
    cfg, _ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 18
minimal_ini = False
encrypt_passwords = False

[Experimental]
experimental = True

[Torznab]
enable_torznab = True
torznab_name = Nyaa
torznab_host = http://prowlarr.example:9696/1/api
torznab_apikey = abc123
torznab_category = 8020
""",
    )
    monkeypatch.setattr(comicarr, "PROVIDER_START_ID", 100, raising=False)

    assert cfg.read(startup=False) is cfg

    migrated = next(entry for entry in cfg.EXTRA_TORZNABS if entry[1] == "http://prowlarr.example:9696/1/api")
    assert migrated[6] == 102  # 101 is reserved by experimental
    assert comicarr.PROVIDER_START_ID == 102


def test_legacy_torznab_name_collision_warns_and_stays_unmigrated(tmp_path, monkeypatch):
    cfg, _ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 18
minimal_ini = False
encrypt_passwords = False

[Torznab]
enable_torznab = True
extra_torznabs = Nyaa, http://other.example:9696/api, False, zzz, 8020, 1, 7
torznab_name = Nyaa
torznab_host = http://prowlarr.example:9696/1/api
torznab_apikey = abc123
torznab_category = 8020
""",
    )
    warn = MagicMock()
    monkeypatch.setattr(config_module.logger, "warn", warn)

    assert cfg.read(startup=False) is cfg

    hosts = [entry[1] for entry in cfg.EXTRA_TORZNABS]
    assert "http://prowlarr.example:9696/1/api" not in hosts
    assert any("reuse the provider name" in call[0][0] for call in warn.call_args_list)


def test_legacy_torznab_name_collision_with_newznab_warns_and_stays_unmigrated(tmp_path, monkeypatch):
    """Provider names share one namespace across newznabs and torznabs — a
    migrated entry reusing a Newznab name would fail provider validation."""
    cfg, _ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 18
minimal_ini = False
encrypt_passwords = False

[Newznab]
extra_newznabs = Nyaa, http://usenet.example:5000/api, False, zzz, 7030, 1, 3

[Torznab]
enable_torznab = True
torznab_name = Nyaa
torznab_host = http://prowlarr.example:9696/1/api
torznab_apikey = abc123
torznab_category = 8020
""",
    )
    warn = MagicMock()
    monkeypatch.setattr(config_module.logger, "warn", warn)

    assert cfg.read(startup=False) is cfg

    hosts = [entry[1] for entry in cfg.EXTRA_TORZNABS]
    assert "http://prowlarr.example:9696/1/api" not in hosts
    assert any("reuse the provider name" in call[0][0] for call in warn.call_args_list)


def test_legacy_torznab_incomplete_fields_warn_and_stay_unmigrated(tmp_path, monkeypatch):
    cfg, _ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 18
minimal_ini = False
encrypt_passwords = False

[Torznab]
torznab_host = http://prowlarr.example:9696/1/api
""",
    )
    warn = MagicMock()
    monkeypatch.setattr(config_module.logger, "warn", warn)

    assert cfg.read(startup=False) is cfg

    assert cfg.EXTRA_TORZNABS == []
    assert warn.called
    assert "NOT used for searching" in warn.call_args_list[0][0][0]


def test_legacy_torznab_absorption_verifies_tls_and_stores_canonical_booleans(tmp_path, monkeypatch):
    """An absorbed entry inherits the operator's fields, not a silent downgrade.

    `TORZNAB_VERIFY` used to default to False, so a legacy entry that said
    nothing about TLS was migrated with verification off. The raw bool was also
    written straight through, reaching the next startup as the string "True" --
    which `search.py` reads as `bool(int(field))` and dies on.
    """
    cfg, ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 18
minimal_ini = False
encrypt_passwords = False

[Torznab]
enable_torznab = True
torznab_name = Nyaa
torznab_host = http://prowlarr.example:9696/1/api
torznab_apikey = abc123
torznab_category = 8020
""",
    )

    assert cfg.read(startup=False) is cfg

    migrated = next(entry for entry in cfg.EXTRA_TORZNABS if entry[1] == "http://prowlarr.example:9696/1/api")
    assert migrated[2] == "1"
    assert migrated[5] == "1"

    # The written config must reread into the same canonical form, because
    # that is the shape the searcher sees on every run after the first.
    reread = configparser.ConfigParser()
    reread.read(ini)
    entries = config_module.parse_provider_extras(reread.get("Torznab", "extra_torznabs"))
    assert entries[0][2] == "1"
    assert bool(int(entries[0][2])) is True


def test_stored_newznab_categories_reach_runtime_unmangled(tmp_path, monkeypatch):
    """get_extras no longer rewrites the category field on its way to runtime.

    It used to turn `1#7030` into `1,7030`, which `search.py` reads as "no
    category configured" -- so every Newznab search fell back to the built-in
    7030 no matter what the operator asked for.
    """
    cfg, _ini = _load_config(
        tmp_path,
        monkeypatch,
        """[General]
config_version = 18
minimal_ini = False
encrypt_passwords = False

[Newznab]
newznab = True
extra_newznabs = Indexer, https://indexer.example/api, 1, abc123, 1#7030#7020, 1, 3

[Torznab]
extra_torznabs =
""",
    )

    assert cfg.read(startup=False) is cfg

    assert cfg.EXTRA_NEWZNABS[0][4] == "1#7030#7020"
    uid, _, categories = cfg.EXTRA_NEWZNABS[0][4].partition("#")
    assert uid == "1"
    assert categories.replace("#", ",") == "7030,7020"
