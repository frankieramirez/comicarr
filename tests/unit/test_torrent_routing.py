#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from pathlib import Path
from types import SimpleNamespace

import pytest

from comicarr.app.downloads import pp_commands, torrent_routing
from comicarr.app.downloads.torrent_routing import QbittorrentDestination

ROUTES = "\n".join(
    [
        "/comics/Magazines | magazines | /downloads/Magazines",
        "/comics/Magazines/Gaming | gaming",
        "/comics/Kids |  | /downloads/Kids",
        "relative/root | nope",
        "/comics/Empty |  |  ",
        "",
    ]
)


def _config(**overrides):
    values = {
        "QBITTORRENT_LABEL": "comics",
        "QBITTORRENT_FOLDER": "/downloads/Comics",
        "QBITTORRENT_ROOT_ROUTES": ROUTES,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _locate(monkeypatch, location):
    monkeypatch.setattr(torrent_routing, "_series_location", lambda _comic_id: location)


def test_parse_routes_skips_unusable_lines():
    routes = torrent_routing.parse_routes(ROUTES)

    assert [(r.root, r.category, r.savepath) for r in routes] == [
        ("/comics/Magazines", "magazines", "/downloads/Magazines"),
        ("/comics/Magazines/Gaming", "gaming", None),
        ("/comics/Kids", None, "/downloads/Kids"),
    ]


@pytest.mark.parametrize(
    "location, expected",
    [
        ("/comics/Magazines/Wizard (1991)", ("magazines", "/downloads/Magazines")),
        ("/comics/Magazines/Gaming/Nintendo Power", ("gaming", "/downloads/Comics")),
        ("/comics/Kids/Bone", ("comics", "/downloads/Kids")),
        ("/comics/Batman (2016)", ("comics", "/downloads/Comics")),
        ("/comics/MagazinesExtra/Foo", ("comics", "/downloads/Comics")),
        (None, ("comics", "/downloads/Comics")),
    ],
)
def test_destination_uses_deepest_matching_root_then_globals(monkeypatch, location, expected):
    _locate(monkeypatch, location)

    assert torrent_routing.qbittorrent_destination(_config(), "4050-1") == QbittorrentDestination(*expected)


def test_no_comic_id_or_no_routes_uses_globals(monkeypatch):
    _locate(monkeypatch, "/comics/Magazines/Wizard")

    assert torrent_routing.qbittorrent_destination(_config(), None) == ("comics", "/downloads/Comics")
    assert torrent_routing.qbittorrent_destination(_config(QBITTORRENT_ROOT_ROUTES=None), "4050-1") == (
        "comics",
        "/downloads/Comics",
    )


@pytest.mark.parametrize("unset", [None, "", "None"])
def test_unset_globals_add_nothing(monkeypatch, unset):
    _locate(monkeypatch, "/comics/Batman")
    config = _config(QBITTORRENT_LABEL=unset, QBITTORRENT_FOLDER=unset)

    assert torrent_routing.qbittorrent_destination(config, "4050-1") == (None, None)


def test_route_save_paths_are_post_processing_roots():
    roots = pp_commands.configured_roots(_config())

    assert Path("/downloads/Magazines") in roots
    assert Path("/downloads/Kids") in roots


def test_qbittorrent_add_uses_routed_category_and_reports_it(monkeypatch):
    import comicarr
    from comicarr.torrent.clients import qbittorrent

    _locate(monkeypatch, "/comics/Magazines/Wizard")
    monkeypatch.setattr(comicarr, "CONFIG", _config(QBITTORRENT_LOADACTION="default"))
    monkeypatch.setattr(qbittorrent.time, "sleep", lambda _seconds: None)
    added = {}

    class FakeClient:
        _is_authenticated = True

        def __init__(self):
            self.present = False

        def get_torrent(self, _hash):
            if not self.present:
                raise RuntimeError("missing")
            return {"save_path": "/downloads/Magazines", "total_size": 1, "addition_date": 0}

        def download_from_link(self, link, **kwargs):
            added.update(kwargs)
            self.present = True

        def get_torrent_files(self, _hash):
            return [{"name": "Wizard 001.cbz"}]

    tc = qbittorrent.TorrentClient()
    tc.client = FakeClient()

    info = tc.load_torrent("magnet:?xt=urn:btih:" + "a" * 40, comicid="4050-1")

    assert added == {"category": "magazines", "savepath": "/downloads/Magazines"}
    assert info["label"] == "magazines"
