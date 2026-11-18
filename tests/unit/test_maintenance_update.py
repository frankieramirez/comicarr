#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""``shutdown(update=True)`` runs the updater (maintenance ``--update``).

The name ``versioncheck`` was not imported in ``comicarr/__init__.py``, so
the update always failed with a NameError that was logged as "failed to
update".
"""

from unittest.mock import MagicMock

import pytest

import comicarr
from comicarr.app.core import lifecycle, runtime
from comicarr.app.system import versioncheck


class _Exited(Exception):
    pass


def test_shutdown_with_update_runs_the_updater(monkeypatch):
    update = MagicMock()
    warn = MagicMock()
    monkeypatch.setattr(versioncheck, "update", update)
    monkeypatch.setattr(comicarr.app.core.logger, "warn", warn)
    monkeypatch.setattr(runtime.current(), "createpid", False, raising=False)
    monkeypatch.setattr(lifecycle.os, "_exit", MagicMock(side_effect=_Exited))

    with pytest.raises(_Exited):
        lifecycle.shutdown(update=True, maintenance=True)

    update.assert_called_once_with()
    warn.assert_not_called()
