#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Migrating a Mylar3 config must not lose every setting to one unknown key.

`_BAD_DEFINITIONS` carried seven entries for NZBsu and DOGnzb -- providers
Mylar3 shipped built in and Comicarr removed. `migrate_mylar3_config` iterates
that dict independently of `_CONFIG_DEFINITIONS`, so a source config with an
`[NZBsu]` or `[DOGnzb]` section produced `values["NZBSU"]`, which has no
definition. `process_kwargs` then raised `KeyError` inside `writeconfig`, and
the caller at `migration.py:369` swallows it as "config migration failed (data
migration succeeded)" -- discarding all 400+ settings and leaving the user on
defaults with a single log line as the only trace.
"""

import configparser

import pytest

from comicarr.config import _BAD_DEFINITIONS, _CONFIG_DEFINITIONS

MYLAR3_CONFIG = """
[General]
annuals_on = True
search_delay = 4

[Import]
comic_dir = /comics

[NZBsu]
nzbsu = True
nzbsu_uid = someuid
nzbsu_apikey = deadbeef

[DOGnzb]
dognzb = True
dognzb_apikey = cafebabe

[Torrents]
enable_tpse = True
"""


def _remapped_values(source_text):
    """The `_BAD_DEFINITIONS` remapping loop from `migrate_mylar3_config`."""
    source = configparser.RawConfigParser()
    source.read_string(source_text)

    values = {}
    for new_key, bad_def in _BAD_DEFINITIONS.items():
        if len(bad_def) < 2:
            continue
        old_section, old_key = bad_def[0], bad_def[1]
        if old_key is None:
            continue
        try:
            raw = source.get(old_section, old_key.lower())
        except (configparser.NoOptionError, configparser.NoSectionError):
            continue
        if raw is not None and new_key not in values:
            values[new_key] = raw.strip()
    return values


class TestBadDefinitionsStayDefinable:
    """Every remapping target must be a key `process_kwargs` can actually define."""

    def test_no_bad_definition_targets_an_undefined_key(self):
        undefined = sorted(key for key in _BAD_DEFINITIONS if key not in _CONFIG_DEFINITIONS)

        assert undefined == [], (
            "_BAD_DEFINITIONS remaps onto keys config cannot define: %s. "
            "migrate_mylar3_config will hand these to writeconfig, process_kwargs "
            "will raise KeyError, and the entire config migration is discarded." % undefined
        )

    def test_mylar3_config_with_removed_providers_yields_only_definable_keys(self):
        values = _remapped_values(MYLAR3_CONFIG)

        undefined = sorted(key for key in values if key not in _CONFIG_DEFINITIONS)

        assert undefined == [], "migrating a Mylar3 config produced undefined keys: %s" % undefined

    def test_the_legacy_rename_still_migrates(self):
        """The guard must not cost us the remappings that do work."""
        values = _remapped_values(MYLAR3_CONFIG)

        assert values.get("ENABLE_PUBLIC") == "True", "enable_tpse -> ENABLE_PUBLIC remapping was lost"

    @pytest.mark.parametrize("definition", _BAD_DEFINITIONS.values())
    def test_every_bad_definition_is_a_2_tuple(self, definition):
        """The 4-tuple form was only ever used by the seven orphaned entries.

        `migration.py` reads `bad_def[0]` and `bad_def[1]` and ignores the rest,
        so a 4-tuple's declared type and default were never consulted anywhere.
        """
        assert len(definition) == 2, "unexpected _BAD_DEFINITIONS arity: %r" % (definition,)


class TestUndefinedKeysAreSkippedNotFatal:
    """Defence in depth: one unknown key must cost only that key."""

    def test_a_stray_key_costs_only_itself(self, tmp_path, monkeypatch):
        """Drives the real `migrate_mylar3_config` with a key nothing defines."""
        import comicarr
        from comicarr import migration

        (tmp_path / "config.ini").write_text(MYLAR3_CONFIG + "\n[Bogus]\nnot_a_real_key = 1\n")

        captured = {}

        class FakeConfig:
            SECURE_DIR = str(tmp_path / ".secure")

            def writeconfig(self, values):
                # Stand in for process_kwargs, which raises on an undefined key.
                for key in values:
                    _CONFIG_DEFINITIONS[key]
                captured.update(values)
                return True

        monkeypatch.setattr(comicarr, "CONFIG", FakeConfig(), raising=False)
        monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path), raising=False)
        monkeypatch.setattr(migration.encrypted, "_get_fernet", lambda: object())

        migration.migrate_mylar3_config(str(tmp_path))

        assert captured, "config migration produced nothing — the write was discarded"
        assert captured["COMIC_DIR"] == "/comics"
        assert captured["ANNUALS_ON"] == "True"
        assert captured["ENABLE_PUBLIC"] == "True", "the enable_tpse remapping must survive"
        assert all(key in _CONFIG_DEFINITIONS for key in captured)


class TestDefineHandlesOnly3Tuples:
    """`_CONFIG_DEFINITIONS` is uniformly 3-tuples, so `_define` need not branch."""

    def test_every_definition_is_a_3_tuple(self):
        wrong = {key: value for key, value in _CONFIG_DEFINITIONS.items() if len(value) != 3}

        assert wrong == {}, "_CONFIG_DEFINITIONS is no longer uniformly 3-tuples: %s" % wrong

    def test_define_unpacks_a_real_key(self):
        from comicarr.config import Config

        key, definition_type, section, ini_key, default = Config._define(object.__new__(Config), "annuals_on")

        assert (key, definition_type, section, ini_key, default) == ("ANNUALS_ON", bool, "General", "annuals_on", False)
