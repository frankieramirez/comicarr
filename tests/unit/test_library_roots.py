#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

import os
from types import SimpleNamespace

from comicarr.app.common import library_roots


def _config(tmp_path, **overrides):
    values = {
        "DESTINATION_DIR": str(tmp_path / "Comics"),
        "MANGA_DESTINATION_DIR": None,
        "COMIC_DIR": None,
        "MANGA_DIR": None,
        "MULTIPLE_DEST_DIRS": None,
        "NEWCOM_DIR": None,
        "ADDITIONAL_LIBRARY_ROOTS": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_additional_roots_are_one_absolute_path_per_line(tmp_path):
    magazines = str(tmp_path / "Magazines")
    kids = str(tmp_path / "Kids")
    config = _config(tmp_path, ADDITIONAL_LIBRARY_ROOTS="%s\n\n  %s  \nrelative/path\n" % (magazines, kids))

    assert library_roots.additional_library_roots(config) == [magazines, kids]
    assert library_roots.configured_library_roots(config) == [str(tmp_path / "Comics"), magazines, kids]


def test_series_folder_must_sit_strictly_below_an_allowed_root(tmp_path):
    magazines = tmp_path / "Magazines"
    (magazines / "Wizard").mkdir(parents=True)
    (tmp_path / "Magazines-old").mkdir()
    config = _config(tmp_path, ADDITIONAL_LIBRARY_ROOTS=str(magazines))

    assert library_roots.is_strict_library_descendant(str(magazines / "Wizard"), config)
    assert library_roots.is_strict_library_descendant(str(tmp_path / "Comics" / "Saga (2012)"), config)
    assert not library_roots.is_strict_library_descendant(str(magazines), config)
    assert not library_roots.is_strict_library_descendant(str(tmp_path / "Magazines-old" / "Wizard"), config)
    assert not library_roots.is_strict_library_descendant(str(magazines / ".." / "elsewhere"), config)
    assert not library_roots.is_strict_library_descendant(os.sep, config)
    assert not library_roots.is_strict_library_descendant(str(tmp_path / "Unlisted" / "Wizard"), config)


def test_symlink_escaping_an_allowed_root_is_refused(tmp_path):
    magazines = tmp_path / "Magazines"
    magazines.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, magazines / "escape")
    config = _config(tmp_path, ADDITIONAL_LIBRARY_ROOTS=str(magazines))

    assert not library_roots.is_strict_library_descendant(str(magazines / "escape"), config)


def test_a_root_that_resolves_to_the_filesystem_root_authorizes_nothing(tmp_path):
    config = _config(tmp_path, ADDITIONAL_LIBRARY_ROOTS=os.sep)

    assert not library_roots.is_strict_library_descendant(str(tmp_path / "anything"), config)


def test_additional_roots_survive_an_ini_write_and_reload(tmp_path, monkeypatch):
    import configparser
    from unittest.mock import MagicMock

    import comicarr
    from comicarr import config as config_module

    secure_dir = tmp_path / "secure"
    secure_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ini = data_dir / "config.ini"
    ini.write_text(
        "[General]\nsecure_dir = %s\nconfig_version = 19\nminimal_ini = False\nencrypt_passwords = False\n"
        % secure_dir,
        encoding="utf-8",
    )
    monkeypatch.setattr(comicarr, "DATA_DIR", str(data_dir), raising=False)
    monkeypatch.setattr(comicarr, "PROG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.setattr("comicarr.maintenance.Maintenance.backup_files", lambda self, **kwargs: True, raising=False)

    def load():
        monkeypatch.setattr(config_module, "config", configparser.ConfigParser())
        cfg = config_module.Config(str(ini))
        cfg.configure = MagicMock()
        cfg.provider_sequence = MagicMock()
        return cfg.read(startup=False)

    roots = "/srv/Magazines\n/srv/Kids 50% Off"
    assert load().writeconfig_values({"additional_library_roots": roots}) is True

    reloaded = load()
    assert reloaded.ADDITIONAL_LIBRARY_ROOTS == roots
    assert library_roots.additional_library_roots(reloaded) == ["/srv/Magazines", "/srv/Kids 50% Off"]


def test_files_are_served_from_library_roots_and_the_arc_and_grab_bag_folders_only(tmp_path):
    for folder in ("Comics/Saga", "Magazines/Wizard", "Arcs", "Elsewhere"):
        (tmp_path / folder).mkdir(parents=True)
    config = _config(
        tmp_path,
        ADDITIONAL_LIBRARY_ROOTS=str(tmp_path / "Magazines"),
        STORYARC_LOCATION=str(tmp_path / "Arcs"),
        GRABBAG_DIR=None,
    )

    assert library_roots.is_servable_library_file(str(tmp_path / "Comics/Saga/Saga 001.cbz"), config)
    assert library_roots.is_servable_library_file(str(tmp_path / "Magazines/Wizard/Wizard 001.cbz"), config)
    assert library_roots.is_servable_library_file(str(tmp_path / "Arcs/Event 001.cbz"), config)
    assert not library_roots.is_servable_library_file(str(tmp_path / "Elsewhere/secret.cbz"), config)
    assert not library_roots.is_servable_library_file("/etc/passwd", _config(tmp_path, ADDITIONAL_LIBRARY_ROOTS=os.sep))
