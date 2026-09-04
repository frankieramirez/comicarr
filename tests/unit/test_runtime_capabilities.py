#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace
from unittest.mock import patch

import comicarr
from comicarr import dependency_check


def _config(tmp_path, unrar_command=None):
    return SimpleNamespace(UNRAR_CMD=unrar_command, CT_SETTINGSPATH=str(tmp_path))


def test_runtime_capabilities_report_an_available_unrar_without_running_pip(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _config(tmp_path), raising=False)
    monkeypatch.setattr(comicarr, "REQS", {}, raising=False)

    diagnostics = dependency_check.RuntimeCapabilityDiagnostics()

    with (
        patch("comicarr.dependency_check.shutil.which", return_value="/usr/local/bin/unrar") as which,
        patch("subprocess.Popen") as popen,
    ):
        diagnostics.loaders()

    which.assert_called_once_with("unrar")
    popen.assert_not_called()
    assert comicarr.REQS["rar"] == {
        "rar_failure": False,
        "rar_message": "/usr/local/bin/unrar",
    }
    assert "pip" not in comicarr.REQS


def test_runtime_capabilities_report_a_missing_unrar_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "CONFIG", _config(tmp_path), raising=False)
    monkeypatch.setattr(comicarr, "REQS", {}, raising=False)

    diagnostics = dependency_check.RuntimeCapabilityDiagnostics()

    with patch("comicarr.dependency_check.shutil.which", return_value=None):
        diagnostics.loaders()

    assert comicarr.REQS["rar"] == {
        "rar_failure": True,
        "rar_message": "Unable to locate unrar",
    }
