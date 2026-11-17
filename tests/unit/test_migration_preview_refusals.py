#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.


"""A refused Mylar3 path says which path and whether it was checked in a container (#1498)."""

from types import SimpleNamespace

import comicarr
from comicarr.app.system import service


def test_missing_folder_names_the_path_and_the_container(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "INSTALL_TYPE", "docker", raising=False)
    missing = str(tmp_path / "mylar3")

    result = service.preview_migration(SimpleNamespace(), missing)

    assert result["success"] is False
    assert result["code"] == "not_a_directory"
    assert result["path"] == missing
    assert result["in_container"] is True
    assert missing in result["error"]
    assert "container" in result["error"]


def test_folder_without_database_has_its_own_code(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "INSTALL_TYPE", "source", raising=False)

    result = service.preview_migration(SimpleNamespace(), str(tmp_path))

    assert result["code"] == "no_database"
    assert result["in_container"] is False
