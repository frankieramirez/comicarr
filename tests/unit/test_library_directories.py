#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Directory creation logging regressions."""

from unittest.mock import MagicMock, patch

from comicarr.app.core import runtime


def test_missing_directory_requested_for_creation_is_not_warned(tmp_path):
    from comicarr.app.library import directories

    destination = tmp_path / "new-series"
    config = MagicMock()
    config.ENFORCE_PERMS = False
    config.CHMOD_DIR = "0777"

    with (
        patch.object(runtime.current(), "config", config),
        patch("comicarr.app.library.directories.logger") as mock_logger,
    ):
        result = directories.validateAndCreateDirectory(str(destination), create=True)

    assert result is True
    assert destination.is_dir()
    warning_text = " ".join(str(part) for call in mock_logger.warn.call_args_list for part in call.args)
    assert "Could not find comic directory" not in warning_text


def test_directory_creation_failure_still_warns(tmp_path):
    from comicarr.app.library import directories

    destination = tmp_path / "uncreatable"
    config = MagicMock()
    config.ENFORCE_PERMS = False
    config.CHMOD_DIR = "0777"

    with (
        patch.object(runtime.current(), "config", config),
        patch("comicarr.app.library.directories.logger") as mock_logger,
        patch("comicarr.app.library.directories.os.makedirs", side_effect=OSError("permission denied")),
    ):
        result = directories.validateAndCreateDirectory(str(destination), create=True)

    assert result is False
    warning_text = " ".join(str(part) for call in mock_logger.warn.call_args_list for part in call.args)
    assert "Could not create directory" in warning_text
