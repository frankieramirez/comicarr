#  Copyright (C) 2025-2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Security regression tests for support carepackage redaction."""

import configparser
import zipfile

import comicarr
from comicarr import config as config_module
from comicarr import encrypted as encrypted_module
from comicarr.carepackage import carePackage


def test_carepackage_redacts_every_encrypted_config_item(tmp_path, monkeypatch):
    """Carepackages should redact the same secrets config encryption protects."""
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "PROG_DIR", str(tmp_path))
    configured_redactions = carePackage().cleaned_list

    for section, key in config_module.ENCRYPTED_CONFIG_ITEMS.values():
        assert (section, key) in configured_redactions


def test_carepackage_clean_config_and_logs_redact_newer_secrets(tmp_path, monkeypatch):
    """Previously omitted encrypted secrets must not appear in bundles or logs."""
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    data_dir.mkdir()
    log_dir.mkdir()

    config_path = data_dir / "config.ini"
    parser = configparser.ConfigParser()
    parser["Logs"] = {"log_dir": str(log_dir)}
    parser["Git"] = {"git_user": "comicarr", "git_branch": "main", "git_token": "github-secret", "git_path": ""}
    parser["Newznab"] = {"extra_newznabs": ""}
    parser["Torznab"] = {"extra_torznabs": ""}
    parser["SLACK"] = {"slack_webhook_url": "slack-secret"}
    parser["MATTERMOST"] = {"mattermost_webhook_url": "mattermost-secret"}
    parser["MATRIX"] = {"matrix_access_token": "matrix-secret"}
    parser["AI"] = {"ai_api_key": "ai-secret"}
    parser["Database"] = {"database_url": "postgres://user:database-secret@example/db"}
    with open(config_path, "w") as config_file:
        parser.write(config_file)

    log_path = log_dir / "comicarr.log"
    log_path.write_text(
        "slack-secret mattermost-secret matrix-secret ai-secret "
        "github-secret postgres://user:database-secret@example/db\n"
    )
    (data_dir / "comicarr.db").write_text("")

    monkeypatch.setattr(comicarr, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(comicarr, "PROG_DIR", str(tmp_path))

    package = carePackage(maintenance=True)
    package.cleaned_config()
    package.filename = str(log_dir / "ComicarrRunningEnvironment.txt")
    package.panicfile = str(log_dir / "carepackage.zip")
    with open(package.filename, "w") as environment_file:
        environment_file.write("environment\n")

    secrets = (
        "slack-secret",
        "mattermost-secret",
        "matrix-secret",
        "ai-secret",
        "database-secret",
        "github-secret",
    )
    expected_redacted_options = (
        ("Git", "git_token"),
        ("SLACK", "slack_webhook_url"),
        ("MATTERMOST", "mattermost_webhook_url"),
        ("MATRIX", "matrix_access_token"),
        ("AI", "ai_api_key"),
        ("Database", "database_url"),
    )

    clean_config_text = (log_dir / "clean_config.ini").read_text()
    for secret in secrets:
        assert secret not in clean_config_text

    clean_parser = configparser.ConfigParser()
    clean_parser.read_string(clean_config_text)
    for section, option in expected_redacted_options:
        assert clean_parser.get(section, option) == "xXX[REMOVED]XXx"

    package.panicbutton()

    with zipfile.ZipFile(log_dir / "carepackage.zip", "r") as bundle:
        redacted_log = bundle.read("comicarr.log").decode("utf-8")
        zip_clean_config = bundle.read("clean_config.ini").decode("utf-8")

    for secret in secrets:
        assert secret not in redacted_log
        assert secret not in zip_clean_config
    assert "-REDACTED-" in redacted_log

    zip_parser = configparser.ConfigParser()
    zip_parser.read_string(zip_clean_config)
    for section, option in expected_redacted_options:
        assert zip_parser.get(section, option) == "xXX[REMOVED]XXx"


def test_encrypt_items_handles_git_token_auth_tuple(tmp_path, monkeypatch):
    """configure() rewrites GIT_TOKEN to a requests auth tuple before encrypt_items.

    encrypt_items must encrypt the string token without AttributeError on .startswith.
    """
    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    config_path = tmp_path / "config.ini"
    config_path.write_text("")

    # Reset Fernet cache so master.key is loaded from this test's SECURE_DIR.
    encrypted_module._fernet_instance = None

    cfg = config_module.Config(str(config_path))
    for attr_name in config_module.ENCRYPTED_CONFIG_ITEMS:
        setattr(cfg, attr_name, None)
    cfg.GIT_TOKEN = ("ghp_test_token_value", "x-oauth-basic")
    cfg.SECURE_DIR = str(secure_dir)
    cfg.WRITE_THE_CONFIG = False

    monkeypatch.setattr(comicarr, "CONFIG", cfg)
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))

    parser = config_module.config
    if not parser.has_section("Git"):
        parser.add_section("Git")

    # Must not raise; must Fernet-encrypt the string token into the parser.
    cfg.encrypt_items(mode="encrypt", updateconfig=True)

    encrypted_token = parser.get("Git", "git_token")
    assert encrypted_token.startswith("gAAAAA")
    assert "ghp_test_token_value" not in encrypted_token
    # Runtime auth tuple shape is unchanged (encrypt writes the parser only).
    assert cfg.GIT_TOKEN == ("ghp_test_token_value", "x-oauth-basic")

    encrypted_module._fernet_instance = None
