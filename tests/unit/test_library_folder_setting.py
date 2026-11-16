#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Settings → General is where a fresh install chooses its library folder."""

import pytest

import comicarr
from comicarr.app.system import service as system_service
from tests.unit.test_system_domain import _make_test_ctx


@pytest.fixture(autouse=True)
def _restore_global_config(monkeypatch):
    # A successful settings save publishes ctx.config as comicarr.CONFIG.
    monkeypatch.setattr(comicarr, "CONFIG", comicarr.CONFIG)


def _ctx(destination=None):
    ctx = _make_test_ctx()
    ctx.config.DESTINATION_DIR = destination
    ctx.config.apply_transaction.return_value = True
    return ctx


def test_a_folder_that_exists_is_saved(tmp_path):
    ctx = _ctx()

    result = system_service.update_config(ctx, {"destination_dir": str(tmp_path)})

    assert result["success"] is True
    assert ctx.config.apply_transaction.call_args.args[0]["DESTINATION_DIR"] == str(tmp_path)


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ("", "Library folder cannot be empty"),
        ("comics", "Library folder must be a full path, such as /comics"),
        ("/no/such/folder/anywhere", "Library folder /no/such/folder/anywhere does not exist on the server"),
    ],
)
def test_a_folder_the_server_cannot_use_is_refused(value, error):
    ctx = _ctx()

    result = system_service.update_config(ctx, {"destination_dir": value})

    assert result == {"success": False, "error": error}
    ctx.config.apply_transaction.assert_not_called()


def test_saving_the_unchanged_folder_never_trips_over_it():
    ctx = _ctx(destination="/was/here/once")

    result = system_service.update_config(ctx, {"destination_dir": "/was/here/once"})

    assert result["success"] is True
