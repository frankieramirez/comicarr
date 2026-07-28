#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Unit tests for the placement stage.

Covers the four modes against the four on-existing policies, arc and non-arc
mechanics, and the fallback paths that `file_ops` never had coverage for: the
EXDEV hardlink drop to copy and the softlink OSError drop to copy.
"""

import errno
import os
from unittest.mock import patch

import pytest

from comicarr.app.common.placement import (
    OnExisting,
    Outcome,
    PlacementError,
    Purpose,
    place,
)

MODES = ("copy", "move", "hardlink", "softlink")


class FakeConfig:
    def __init__(self, file_opts="move", arc_fileops="copy", relative=False):
        self.FILE_OPTS = file_opts
        self.ARC_FILEOPS = arc_fileops
        self.ARC_FILEOPS_SOFTLINK_RELATIVE = relative


@pytest.fixture
def paths(tmp_path):
    source = tmp_path / "src" / "Saga 001.cbz"
    source.parent.mkdir()
    source.write_bytes(b"payload")
    destination = tmp_path / "dst" / "Saga 001.cbz"
    destination.parent.mkdir()
    return str(source), str(destination)


# ---------------------------------------------------------------------------
# Mode resolution: the reason this module exists
# ---------------------------------------------------------------------------


class TestModeIsReadAtCallTime:
    def test_series_and_import_read_file_opts(self, paths):
        source, destination = paths
        config = FakeConfig(file_opts="copy", arc_fileops="hardlink")

        result = place(source, destination, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=config)

        assert result.effective_mode == "copy"

    def test_one_off_and_arc_read_arc_fileops(self, paths):
        source, destination = paths
        config = FakeConfig(file_opts="move", arc_fileops="copy")

        result = place(source, destination, Purpose.ONE_OFF, on_existing=OnExisting.UNGUARDED, config=config)

        assert result.effective_mode == "copy"
        assert os.path.exists(source), "one-off copy must not consume the source"

    def test_multiple_forces_copy_for_one_off(self, paths):
        source, destination = paths
        config = FakeConfig(arc_fileops="move")

        result = place(
            source,
            destination,
            Purpose.ONE_OFF,
            on_existing=OnExisting.UNGUARDED,
            multiple=True,
            config=config,
        )

        assert result.effective_mode == "copy"
        assert os.path.exists(source)

    def test_a_config_mutated_after_import_is_still_honoured(self, paths):
        """The #303 invariant. Nothing may capture the mode before the call."""
        source, destination = paths
        config = FakeConfig(file_opts="move")
        config.FILE_OPTS = "hardlink"

        result = place(source, destination, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=config)

        assert result.effective_mode == "hardlink"
        assert os.path.exists(source)

    def test_place_has_no_parameter_that_accepts_a_mode(self):
        import inspect

        from comicarr.app.common import placement

        parameters = set(inspect.signature(placement.place).parameters)

        assert "mode" not in parameters
        assert "file_opts" not in parameters
        assert "os_detect" not in parameters, "dropped as dead in #334"

    def test_unsupported_mode_raises(self, paths):
        source, destination = paths

        with pytest.raises(PlacementError):
            place(
                source,
                destination,
                Purpose.SERIES,
                on_existing=OnExisting.UNGUARDED,
                config=FakeConfig(file_opts="teleport"),
            )


# ---------------------------------------------------------------------------
# Source survival, per mode and purpose
# ---------------------------------------------------------------------------


class TestSourceSurvival:
    @pytest.mark.parametrize("mode", ("copy", "hardlink", "softlink"))
    def test_non_move_modes_leave_the_source_in_place(self, paths, mode):
        source, destination = paths

        result = place(
            source, destination, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=FakeConfig(file_opts=mode)
        )

        assert os.path.lexists(source)
        assert result.source_survived is True
        assert os.path.exists(destination)

    def test_move_consumes_the_source(self, paths):
        source, destination = paths

        result = place(
            source, destination, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=FakeConfig(file_opts="move")
        )

        assert not os.path.exists(source)
        assert result.source_survived is False
        assert result.effective_mode == "move"

    def test_non_arc_softlink_leaves_a_symlink_at_the_source(self, paths):
        """The sharp edge: the source path survives, but as a link into the library."""
        source, destination = paths

        result = place(
            source,
            destination,
            Purpose.SERIES,
            on_existing=OnExisting.UNGUARDED,
            config=FakeConfig(file_opts="softlink"),
        )

        assert result.source_survived is True
        assert result.source_is_symlink is True
        assert os.path.islink(source)
        assert os.path.realpath(source) == os.path.realpath(destination)

    def test_arc_softlink_leaves_the_source_untouched(self, paths):
        source, destination = paths

        result = place(
            source,
            destination,
            Purpose.ARC,
            on_existing=OnExisting.UNGUARDED,
            config=FakeConfig(arc_fileops="softlink"),
        )

        assert result.source_is_symlink is False
        assert not os.path.islink(source)
        assert os.path.islink(destination)

    def test_arc_move_degrades_to_copy_to_keep_the_series_file(self, paths):
        source, destination = paths

        result = place(
            source, destination, Purpose.ARC, on_existing=OnExisting.UNGUARDED, config=FakeConfig(arc_fileops="move")
        )

        assert result.effective_mode == "copy"
        assert os.path.exists(source)

    def test_arc_relative_softlink_is_relative(self, paths):
        source, destination = paths

        place(
            source,
            destination,
            Purpose.ARC,
            on_existing=OnExisting.UNGUARDED,
            config=FakeConfig(arc_fileops="softlink", relative=True),
        )

        assert not os.path.isabs(os.readlink(destination))
        assert os.path.exists(destination)


# ---------------------------------------------------------------------------
# Fallbacks -- the paths file_ops never had coverage for
# ---------------------------------------------------------------------------


class TestFallbacks:
    def test_hardlink_drops_to_copy_on_exdev(self, paths):
        source, destination = paths

        with patch("comicarr.app.common.placement.os.link", side_effect=OSError(errno.EXDEV, "cross-device")):
            result = place(
                source,
                destination,
                Purpose.SERIES,
                on_existing=OnExisting.UNGUARDED,
                config=FakeConfig(file_opts="hardlink"),
            )

        assert result.effective_mode == "copy", "the caller must be able to see the link never happened"
        assert os.path.exists(destination)
        assert os.path.exists(source)

    def test_hardlink_failure_that_is_not_exdev_raises(self, paths):
        source, destination = paths

        with patch("comicarr.app.common.placement.os.link", side_effect=OSError(errno.EPERM, "no hardlinks here")):
            with pytest.raises(PlacementError):
                place(
                    source,
                    destination,
                    Purpose.SERIES,
                    on_existing=OnExisting.UNGUARDED,
                    config=FakeConfig(file_opts="hardlink"),
                )

    def test_arc_softlink_drops_to_copy_when_symlink_fails(self, paths):
        source, destination = paths

        with patch("comicarr.app.common.placement.os.symlink", side_effect=OSError("nope")):
            result = place(
                source,
                destination,
                Purpose.ARC,
                on_existing=OnExisting.UNGUARDED,
                config=FakeConfig(arc_fileops="softlink"),
            )

        assert result.effective_mode == "copy"
        assert os.path.exists(destination)
        assert not os.path.islink(destination)

    def test_a_failed_fallback_still_raises(self, paths):
        source, destination = paths

        with (
            patch("comicarr.app.common.placement.os.link", side_effect=OSError(errno.EXDEV, "cross-device")),
            patch("comicarr.app.common.placement.shutil.copy", side_effect=OSError("disk full")),
        ):
            with pytest.raises(PlacementError):
                place(
                    source,
                    destination,
                    Purpose.SERIES,
                    on_existing=OnExisting.UNGUARDED,
                    config=FakeConfig(file_opts="hardlink"),
                )


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


class TestUnguarded:
    @pytest.mark.parametrize("mode", ("copy", "move", "softlink"))
    def test_three_of_four_modes_replace_the_destination(self, paths, mode):
        """Measured behaviour, preserved deliberately. Only hardlink refuses."""
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"stale")

        place(source, destination, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=FakeConfig(file_opts=mode))

        assert open(destination, "rb").read() == b"payload"

    def test_hardlink_alone_refuses_an_existing_destination(self, paths):
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"stale")

        with pytest.raises(PlacementError):
            place(
                source,
                destination,
                Purpose.SERIES,
                on_existing=OnExisting.UNGUARDED,
                config=FakeConfig(file_opts="hardlink"),
            )

        assert open(destination, "rb").read() == b"stale"

    def test_never_reports_already_placed(self, paths):
        source, destination = paths
        os.link(source, destination)

        result = place(
            source, destination, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=FakeConfig(file_opts="move")
        )

        assert result.outcome is Outcome.PLACED


class TestSkip:
    def test_an_existing_file_means_no_placement_and_no_error(self, paths):
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"already here")

        result = place(
            source, destination, Purpose.ARC, on_existing=OnExisting.SKIP, config=FakeConfig(arc_fileops="copy")
        )

        assert result.outcome is Outcome.ALREADY_PLACED
        assert result.source_survived is True
        assert open(destination, "rb").read() == b"already here"

    def test_a_dangling_symlink_is_not_a_file_so_placement_proceeds(self, paths):
        """isfile, not lexists -- matches the storyarcs guard exactly."""
        source, destination = paths
        target = os.path.join(os.path.dirname(destination), "gone.cbz")
        os.symlink(target, destination)

        result = place(
            source, destination, Purpose.ARC, on_existing=OnExisting.SKIP, config=FakeConfig(arc_fileops="copy")
        )

        assert result.outcome is Outcome.PLACED, "SKIP must not short-circuit on a dangling symlink"
        assert open(target, "rb").read() == b"payload"

    def test_an_empty_destination_places_normally(self, paths):
        source, destination = paths

        result = place(
            source, destination, Purpose.ARC, on_existing=OnExisting.SKIP, config=FakeConfig(arc_fileops="copy")
        )

        assert result.outcome is Outcome.PLACED
        assert os.path.exists(destination)


class TestDisplace:
    def test_an_already_placed_file_short_circuits(self, paths):
        source, destination = paths
        os.link(source, destination)

        result = place(
            source,
            destination,
            Purpose.SERIES,
            on_existing=OnExisting.DISPLACE,
            config=FakeConfig(file_opts="hardlink"),
        )

        assert result.outcome is Outcome.ALREADY_PLACED
        assert os.path.exists(source)

    @pytest.mark.parametrize("mode", MODES)
    def test_a_different_file_is_replaced_under_every_mode(self, paths, mode):
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"stale")

        result = place(
            source, destination, Purpose.SERIES, on_existing=OnExisting.DISPLACE, config=FakeConfig(file_opts=mode)
        )

        assert result.outcome is Outcome.PLACED
        assert open(destination, "rb").read() == b"payload"

    def test_the_displaced_marker_is_cleaned_up_on_success(self, paths):
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"stale")

        place(source, destination, Purpose.SERIES, on_existing=OnExisting.DISPLACE, config=FakeConfig(file_opts="copy"))

        assert not os.path.exists(destination + ".comicarr-displaced")

    def test_a_failed_placement_restores_the_previous_file(self, paths):
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"the copy the operator already had")

        with patch("comicarr.app.common.placement.shutil.copy", side_effect=OSError("disk full")):
            with pytest.raises(PlacementError):
                place(
                    source,
                    destination,
                    Purpose.SERIES,
                    on_existing=OnExisting.DISPLACE,
                    config=FakeConfig(file_opts="copy"),
                )

        assert open(destination, "rb").read() == b"the copy the operator already had"
        assert not os.path.exists(destination + ".comicarr-displaced")

    def test_an_orphaned_marker_is_clobbered_rather_than_stranding_the_file(self, paths):
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"stale")
        with open(destination + ".comicarr-displaced", "wb") as handle:
            handle.write(b"orphan from an earlier crash")

        result = place(
            source, destination, Purpose.SERIES, on_existing=OnExisting.DISPLACE, config=FakeConfig(file_opts="copy")
        )

        assert result.outcome is Outcome.PLACED
        assert open(destination, "rb").read() == b"payload"

    def test_a_failed_displace_raises_before_placing(self, paths):
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"stale")

        with patch("comicarr.app.common.placement.os.replace", side_effect=OSError("read-only")):
            with pytest.raises(PlacementError):
                place(
                    source,
                    destination,
                    Purpose.SERIES,
                    on_existing=OnExisting.DISPLACE,
                    config=FakeConfig(file_opts="copy"),
                )

        assert open(destination, "rb").read() == b"stale"


class TestRefuse:
    @pytest.mark.parametrize("mode", MODES)
    def test_an_existing_destination_is_never_replaced(self, paths, mode):
        source, destination = paths
        with open(destination, "wb") as handle:
            handle.write(b"the operator's file")

        with pytest.raises(PlacementError):
            place(source, destination, Purpose.IMPORT, on_existing=OnExisting.REFUSE, config=FakeConfig(file_opts=mode))

        assert open(destination, "rb").read() == b"the operator's file"
        assert os.path.exists(source), "a refused placement must not consume the source"

    @pytest.mark.parametrize("mode", ("copy", "hardlink", "softlink"))
    def test_source_preserving_modes_keep_the_source_as_a_real_file(self, paths, mode):
        source, destination = paths

        result = place(
            source, destination, Purpose.IMPORT, on_existing=OnExisting.REFUSE, config=FakeConfig(file_opts=mode)
        )

        assert result.source_survived is True
        assert result.source_is_symlink is False, "an import must not replace the inbox file with a link"
        assert not os.path.islink(source)
        assert os.path.exists(destination)

    def test_move_consumes_the_source(self, paths):
        source, destination = paths

        result = place(
            source, destination, Purpose.IMPORT, on_existing=OnExisting.REFUSE, config=FakeConfig(file_opts="move")
        )

        assert result.source_survived is False
        assert not os.path.exists(source)
        assert open(destination, "rb").read() == b"payload"

    def test_move_publishes_through_a_temporary_file_across_filesystems(self, paths):
        source, destination = paths
        real_link = os.link
        calls = []

        def link_once_exdev(src, dst, *args, **kwargs):
            calls.append((src, dst))
            if len(calls) == 1:
                raise OSError(errno.EXDEV, "cross-device")
            return real_link(src, dst, *args, **kwargs)

        with patch("comicarr.app.common.placement.os.link", side_effect=link_once_exdev):
            result = place(
                source, destination, Purpose.IMPORT, on_existing=OnExisting.REFUSE, config=FakeConfig(file_opts="move")
            )

        assert result.effective_mode == "move", "a cross-filesystem move is still a move"
        assert not os.path.exists(source)
        assert open(destination, "rb").read() == b"payload"
        assert not [
            name for name in os.listdir(os.path.dirname(destination)) if name.startswith(".comicarr-import-")
        ], "the temporary file must not be left behind"

    def test_hardlink_degrades_to_an_atomic_copy_across_filesystems(self, paths):
        source, destination = paths
        real_link = os.link
        calls = []

        def link_first_exdev(src, dst, *args, **kwargs):
            calls.append((src, dst))
            if len(calls) == 1:
                raise OSError(errno.EXDEV, "cross-device")
            return real_link(src, dst, *args, **kwargs)

        with patch("comicarr.app.common.placement.os.link", side_effect=link_first_exdev):
            result = place(
                source,
                destination,
                Purpose.IMPORT,
                on_existing=OnExisting.REFUSE,
                config=FakeConfig(file_opts="hardlink"),
            )

        assert result.effective_mode == "copy"
        assert result.source_survived is True
        assert os.path.exists(source)
        assert open(destination, "rb").read() == b"payload"

    def test_a_failed_source_unlink_undoes_the_publish(self, paths):
        source, destination = paths

        real_unlink = os.unlink

        def refuse_to_unlink_the_source(path, *args, **kwargs):
            if path == source:
                raise OSError("busy")
            return real_unlink(path, *args, **kwargs)

        with patch("comicarr.app.common.placement.os.unlink", side_effect=refuse_to_unlink_the_source):
            with pytest.raises(PlacementError):
                place(
                    source,
                    destination,
                    Purpose.IMPORT,
                    on_existing=OnExisting.REFUSE,
                    config=FakeConfig(file_opts="move"),
                )

        assert os.path.exists(source), "the source must survive a failed move"
        assert not os.path.exists(destination), "source and destination must never both exist"

    def test_never_reports_already_placed_even_for_the_same_file(self, paths):
        """REFUSE refuses a same-file destination; it is a conflict, not a success."""
        source, destination = paths
        os.link(source, destination)

        with pytest.raises(PlacementError):
            place(
                source,
                destination,
                Purpose.IMPORT,
                on_existing=OnExisting.REFUSE,
                config=FakeConfig(file_opts="hardlink"),
            )


# ---------------------------------------------------------------------------
# The failure contract
# ---------------------------------------------------------------------------


class TestFailuresAlwaysRaise:
    def test_placement_error_is_an_oserror(self):
        assert issubclass(PlacementError, OSError)

    def test_a_narrow_oserror_handler_still_catches_it(self, paths):
        """storyarcs catches (OSError, IOError); migration must stay mechanical."""
        source, destination = paths

        caught = False
        try:
            place(
                source,
                destination,
                Purpose.SERIES,
                on_existing=OnExisting.UNGUARDED,
                config=FakeConfig(file_opts="move"),
            )
            place(
                source,
                destination,
                Purpose.SERIES,
                on_existing=OnExisting.UNGUARDED,
                config=FakeConfig(file_opts="move"),
            )
        except (OSError, IOError):
            caught = True

        assert caught

    def test_the_error_carries_the_context_a_log_line_needs(self, paths):
        source, destination = paths

        with pytest.raises(PlacementError) as excinfo:
            place(
                source,
                destination,
                Purpose.IMPORT,
                on_existing=OnExisting.UNGUARDED,
                config=FakeConfig(file_opts="teleport"),
            )

        assert excinfo.value.purpose is Purpose.IMPORT
        assert excinfo.value.mode == "teleport"
        assert excinfo.value.source == source
        assert excinfo.value.destination == destination

    def test_no_placement_returns_a_falsy_value(self, paths):
        """The swallow-and-return-False shape is what let #303 stay invisible."""
        source, destination = paths

        result = place(
            source, destination, Purpose.SERIES, on_existing=OnExisting.UNGUARDED, config=FakeConfig(file_opts="copy")
        )

        assert result


class TestOnExistingIsRequired:
    def test_place_refuses_to_run_without_a_policy(self, paths):
        source, destination = paths

        with pytest.raises(TypeError):
            place(source, destination, Purpose.SERIES, config=FakeConfig())
