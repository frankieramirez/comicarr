#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Live dialect coverage for Support bundle aggregate projections."""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData, insert
from sqlalchemy.engine import make_url

import comicarr
from comicarr.app.acquisition.maintenance import ensure_acquisition_schema
from comicarr.app.core.context import AppContext
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.schema import upgrade_database
from comicarr.app.core.tables import annuals, comics, issues
from comicarr.app.system import support_bundle as sb

pytestmark = pytest.mark.slow

FIXED_CLOCK = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)


def _reset_database(engine):
    reflected = MetaData()
    reflected.reflect(bind=engine)
    reflected.drop_all(bind=engine)


def _config():
    return SimpleNamespace(
        POST_PROCESSING=True,
        ENABLE_RSS=True,
        CHECK_GITHUB=True,
        COMICVINE_ENABLED=True,
        COMICVINE_API="dialect-secret-must-not-leak",
        USE_METRON_SEARCH=False,
        METRON_USERNAME=None,
        METRON_PASSWORD=None,
        MANGADEX_ENABLED=True,
        MAL_ENABLED=False,
        MAL_CLIENT_ID=None,
        AI_BASE_URL=None,
        AI_API_KEY=None,
        AI_MODEL=None,
        ENABLE_DDL=True,
        ENABLE_GETCOMICS=True,
        ENABLE_EXTERNAL_SERVER=False,
        EXPERIMENTAL=False,
        NEWZNAB=True,
        EXTRA_NEWZNABS=[["nn", "http://secret.example", "k", 1, "c", "1"]],
        NZB_DOWNLOADER=0,
        SAB_HOST="http://secret-sab.example",
        SAB_APIKEY="sab-secret",
        SAB_DIRECTORY="/secret/sab",
        ENABLE_PUBLIC=False,
        ENABLE_32P=False,
        ENABLE_TORZNAB=False,
        EXTRA_TORZNABS=[],
        ENABLE_TORRENT_SEARCH=False,
        ENABLE_TORRENTS=False,
        TORRENT_DOWNLOADER=0,
        DDL_LOCATION="/secret/ddl",
        BLACKHOLE_DIR=None,
        NZBGET_HOST=None,
        NZBGET_DIRECTORY=None,
        LOCAL_WATCHDIR=None,
        UTORRENT_HOST=None,
        RTORRENT_HOST=None,
        RTORRENT_DIRECTORY=None,
        TRANSMISSION_HOST=None,
        TRANSMISSION_DIRECTORY=None,
        DELUGE_HOST=None,
        DELUGE_DOWNLOAD_DIRECTORY=None,
        QBITTORRENT_HOST=None,
        QBITTORRENT_FOLDER=None,
    )


def _expected_dialect(url: str) -> str:
    name = make_url(url).get_backend_name()
    if name.startswith("postgres"):
        return "postgresql"
    if name.startswith("mysql"):
        return "mysql"
    return "sqlite"


def test_support_bundle_projection_equivalent_across_dialects(monkeypatch, tmp_path):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set")

    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(comicarr, "CONFIG", None, raising=False)
    monkeypatch.setenv("DATABASE_URL", database_url)
    shutdown_engine()

    engine = get_engine()
    try:
        _reset_database(engine)
        upgrade_database(engine)
        assert ensure_acquisition_schema(engine).ready

        with engine.begin() as conn:
            conn.execute(
                insert(comics).values(
                    ComicID="dialect-series",
                    ComicName="Dialect Secret Title",
                )
            )
            for i in range(3):
                conn.execute(
                    insert(issues).values(
                        IssueID=f"dialect-issue-{i}",
                        ComicID="dialect-series",
                        ComicName="Dialect Secret Title",
                        Status="Wanted" if i == 0 else "Downloaded",
                    )
                )
            conn.execute(
                insert(annuals).values(
                    IssueID="dialect-annual-1",
                    ComicID="dialect-series",
                    ComicName="Dialect Secret Annual",
                    Status="Wanted",
                )
            )

        ctx = AppContext(
            prog_dir=str(tmp_path),
            data_dir=str(tmp_path / "data"),
            db_file=str(tmp_path / "data" / "comicarr.db"),
            config=_config(),
            current_version_name="0.27.0",
            install_type="docker",
            scheduler=SimpleNamespace(get_jobs=lambda: []),
            disposed=False,
        )
        artifact = sb.generate_support_bundle(ctx, clock=lambda: FIXED_CLOCK)
        assert artifact.status in {"complete", "partial"}

        with zipfile.ZipFile(io.BytesIO(artifact.content)) as zf:
            diagnostics = json.loads(zf.read("diagnostics.json"))
            blob = b"".join(zf.read(n) for n in zf.namelist())
            text_blob = blob.decode("utf-8", errors="replace")
            assert "Dialect Secret Title" not in text_blob
            assert "dialect-secret" not in text_blob.lower()
            assert "sab-secret" not in text_blob
            # Masked or full credentialed URLs must never appear.
            assert "://comicarr:comicarr@" not in text_blob
            assert "postgresql://comicarr" not in text_blob

            assert diagnostics["runtime"]["database_dialect"] == _expected_dialect(database_url)

            if "database" in diagnostics:
                buckets = diagnostics["database"]["count_buckets"]
                assert buckets["series"] == "one"
                assert buckets["issues"] == "2_9"
                assert buckets["annuals"] == "one"
                assert buckets["wanted"] == "2_9"
                assert diagnostics["database"]["acquisition_schema_state"] == "ready"
                assert diagnostics["database"]["acquisition_schema_version"] >= 7
    finally:
        shutdown_engine()
