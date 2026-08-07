#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""CONFIG_VERSION migrations: 15 → 16 (CHECK_GITHUB) and 16 → 17 (host_return)."""

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

    assert cfg.CONFIG_VERSION == 17
    assert cfg.CHECK_GITHUB is True
    assert REGISTRY["CHECK_GITHUB"].default is True
    assert REGISTRY["CONFIG_VERSION"].default == 17
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

    assert cfg.CONFIG_VERSION == 17
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

    assert cfg.CONFIG_VERSION == 17
    assert "HOST_RETURN" not in REGISTRY
    assert not hasattr(cfg, "HOST_RETURN")

    text = ini.read_text(encoding="utf-8").lower()
    assert "host_return" not in text
    # Neighbouring keys in the same section survive the scrub.
    assert "http_port" in text
