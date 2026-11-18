#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Print copies on the shelf: storage, validation, routes, and the wall to search."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select

from comicarr.app.core import runtime
from comicarr.app.core.db import get_engine, shutdown_engine
from comicarr.app.core.security import require_session
from comicarr.app.core.tables import annuals, comics, issues, metadata, physical_copies
from comicarr.app.shelf import service
from comicarr.app.shelf.router import router


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.current(), "data_dir", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if runtime.current().log_level is None:
        monkeypatch.setattr(runtime.current(), "log_level", 0, raising=False)
    engine = get_engine()
    metadata.create_all(engine)
    with engine.begin() as conn:
        for row in (
            {
                "ComicID": "100",
                "ComicName": "Starfall Saga",
                "ComicImageURL": "https://img.example/series.jpg",
                "ContentType": "comic",
                "Type": "Print",
            },
            {"ComicID": "200", "ComicName": "Starfall Saga TPB", "ContentType": "comic", "Type": "TPB"},
            {"ComicID": "md-1", "ComicName": "Paper Tigers", "ContentType": "manga"},
        ):
            conn.execute(insert(comics).values(**row))
        for row in (
            {
                "IssueID": "i64",
                "ComicID": "100",
                "Issue_Number": "64",
                "IssueName": "Chapter Sixty-Four",
                "Status": "Downloaded",
                "ImageURL": "https://img.example/64.jpg",
            },
            {"IssueID": "i65", "ComicID": "100", "Issue_Number": "65", "Status": "Wanted"},
            {"IssueID": "t1", "ComicID": "200", "Issue_Number": "1", "Status": "Skipped"},
        ):
            conn.execute(insert(issues).values(**row))
        conn.execute(insert(annuals), [{"IssueID": "a1", "ComicID": "100", "Issue_Number": "1", "Status": "Skipped"}])
    yield
    shutdown_engine()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: "operator"
    with TestClient(app) as test_client:
        yield test_client


def _issue_copy(**fields):
    return service.create_copy({"ComicID": "100", "ItemID": "i64", **fields})


def test_two_covers_of_one_issue_are_two_copies():
    standard = _issue_copy(Grade="NM", PaidCents=499, Storage="Long box 03")
    virgin = _issue_copy(VariantName="1:25 virgin", Grade="CGC 9.8", PaidCents=6000)

    assert standard["CopyID"] != virgin["CopyID"]
    assert virgin["Grade"] == "CGC 9.8"
    assert standard["SeriesName"] == "Starfall Saga"
    assert standard["ItemLabel"] == "#64 · Chapter Sixty-Four"
    assert standard["CoverURL"] == "https://img.example/64.jpg"
    assert service.series_shelf("100") == {"issues": {"i64": 2}, "volumes": {}}
    listed = service.list_copies(comic_id="100", item_id="i64")
    assert listed["total"] == 2
    assert listed["paid_cents"] == 6499


def test_a_copy_never_touches_the_issue_status():
    _issue_copy()
    service.create_copy({"ComicID": "100", "ItemID": "i65"})
    with get_engine().connect() as conn:
        statuses = dict(conn.execute(select(issues.c.IssueID, issues.c.Status)).all())
    assert statuses == {"i64": "Downloaded", "i65": "Wanted", "t1": "Skipped"}


def test_a_manga_volume_is_addressed_by_its_number():
    volume = service.create_copy({"ComicID": "md-1", "VolumeNumber": "01"})
    assert volume["VolumeNumber"] == "1"
    assert volume["ItemID"] is None
    assert volume["ItemLabel"] == "Vol. 1"
    assert service.series_shelf("md-1") == {"issues": {}, "volumes": {"1": 1}}
    assert service.list_copies(comic_id="md-1", volume_number="1")["total"] == 1


def test_an_annual_is_addressed_like_an_issue():
    copy = service.create_copy({"ComicID": "100", "ItemID": "a1"})
    assert copy["ItemLabel"] == "#1"
    assert service.series_shelf("100")["issues"] == {"a1": 1}


@pytest.mark.parametrize(
    ("body", "code", "field"),
    [
        ({"ComicID": "nope", "ItemID": "i64"}, "series_not_found", None),
        ({"ComicID": "100", "ItemID": "missing"}, "item_not_found", None),
        ({"ComicID": "100", "ItemID": "t1"}, "item_not_found", None),
        ({"ComicID": "100"}, "invalid_field", "ItemID"),
        ({"ComicID": "100", "VolumeNumber": "1"}, "volume_needs_manga", "VolumeNumber"),
        ({"ComicID": "md-1", "VolumeNumber": "x" * 33}, "invalid_field", "VolumeNumber"),
        ({"ComicID": "md-1", "ItemID": "i64", "VolumeNumber": "1"}, "invalid_field", "VolumeNumber"),
        ({"ComicID": "100", "ItemID": "i64", "PaidCents": -1}, "invalid_field", "PaidCents"),
        ({"ComicID": "100", "ItemID": "i64", "PaidCents": 4.99}, "invalid_field", "PaidCents"),
        ({"ComicID": "100", "ItemID": "i64", "Grade": 9.8}, "invalid_field", "Grade"),
        ({"ComicID": "100", "ItemID": "i64", "Notes": "x" * 4001}, "field_too_long", "Notes"),
        ({"ComicID": "100", "ItemID": "i64", "Owner": "me"}, "unknown_field", "Owner"),
    ],
)
def test_bad_input_is_refused_with_a_code(body, code, field):
    with pytest.raises(service.CopyError) as caught:
        service.create_copy(body)
    assert caught.value.code == code
    assert caught.value.field == field
    with get_engine().connect() as conn:
        assert conn.execute(select(physical_copies)).first() is None


def test_the_copy_outlives_its_series_and_relinks_when_it_returns():
    _issue_copy(VariantName="1:25 virgin")
    with get_engine().begin() as conn:
        conn.execute(delete(issues).where(issues.c.ComicID == "100"))
        conn.execute(delete(comics).where(comics.c.ComicID == "100"))

    orphan = service.list_copies(query="starfall")["results"][0]
    assert orphan["SeriesPresent"] is False
    assert orphan["SeriesName"] == "Starfall Saga"
    assert orphan["ItemLabel"] == "#64 · Chapter Sixty-Four"

    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID="100", ComicName="Starfall Saga (2012)"))
    back = service.list_copies(comic_id="100")["results"][0]
    assert back["SeriesPresent"] is True
    assert back["SeriesName"] == "Starfall Saga (2012)"


def test_update_changes_what_is_recorded_but_not_the_item():
    copy = _issue_copy(Grade="VF")
    updated = service.update_copy(copy["CopyID"], {"Grade": "", "Storage": "  Slab shelf "})
    assert updated["Grade"] is None
    assert updated["Storage"] == "Slab shelf"
    assert updated["ItemID"] == "i64"
    with pytest.raises(service.CopyError) as caught:
        service.update_copy(copy["CopyID"], {"ItemID": "i65"})
    assert caught.value.code == "unknown_field"
    with pytest.raises(service.CopyError) as caught:
        service.update_copy("missing", {"Notes": "x"})
    assert caught.value.status == 404


def test_bulk_mark_adds_one_copy_where_there_is_none():
    _issue_copy(VariantName="Cover B")
    assert service.mark_items("100", {"ItemIDs": ["i64", "i65", "a1", "i65"]}) == {"created": 2, "skipped": 2}
    assert service.series_shelf("100")["issues"] == {"i64": 1, "i65": 1, "a1": 1}
    assert service.mark_items("md-1", {"VolumeNumbers": ["1", "02"]}) == {"created": 2, "skipped": 0}
    assert service.series_shelf("md-1")["volumes"] == {"1": 1, "2": 1}


def test_bulk_mark_is_all_or_nothing():
    with pytest.raises(service.CopyError):
        service.mark_items("100", {"ItemIDs": ["i64", "missing"]})
    with pytest.raises(service.CopyError):
        service.mark_items("100", {"ItemIDs": []})
    assert service.series_shelf("100") == {"issues": {}, "volumes": {}}


def test_search_reaches_the_storage_place_and_pages_keep_the_full_total():
    _issue_copy(Storage="Long box 03", PaidCents=499)
    _issue_copy(Storage="Slab shelf", PaidCents=1000)
    service.create_copy({"ComicID": "md-1", "VolumeNumber": "2", "Storage": "Shelf B"})

    assert service.list_copies(comic_id="100")["total"] == 2
    assert service.list_copies(query="long box")["paid_cents"] == 499
    assert service.list_copies(query="paper tig")["total"] == 1
    page = service.list_copies(limit=1)
    assert len(page["results"]) == 1
    assert page["total"] == 3
    assert page["paid_cents"] == 1499


def test_routes_round_trip_and_return_codes(client):
    created = client.post("/api/shelf/copies", json={"ComicID": "100", "ItemID": "i64"})
    assert created.status_code == 201
    copy_id = created.json()["CopyID"]

    patched = client.patch("/api/shelf/copies/%s" % copy_id, json={"Grade": "9.6"})
    assert patched.status_code == 200 and patched.json()["Grade"] == "9.6"

    refused = client.patch("/api/shelf/copies/%s" % copy_id, json={"PaidCents": "4.99"})
    assert refused.status_code == 400
    assert refused.json() == {"detail": "invalid_field", "code": "invalid_field", "field": "PaidCents"}

    missing = client.post("/api/shelf/copies", json={"ComicID": "nope", "ItemID": "x"})
    assert missing.status_code == 404 and missing.json()["code"] == "series_not_found"

    marked = client.post("/api/shelf/series/100/mark", json={"ItemIDs": ["i64", "i65"]})
    assert marked.json() == {"created": 1, "skipped": 1}
    assert client.get("/api/shelf/series/100").json() == {"issues": {"i64": 1, "i65": 1}, "volumes": {}}
    assert client.get("/api/shelf/copies", params={"item_id": "i65"}).json()["total"] == 1

    assert client.delete("/api/shelf/copies/%s" % copy_id).status_code == 204
    assert client.delete("/api/shelf/copies/%s" % copy_id).status_code == 404


def test_export_is_one_row_per_copy_and_defuses_formulas(client):
    _issue_copy(VariantName="=HYPERLINK(1)", PaidCents=6005, Storage="Long box 03")
    service.create_copy({"ComicID": "md-1", "VolumeNumber": "2"})

    exported = client.get("/api/shelf/export.csv")
    assert exported.headers["content-type"] == "text/csv; charset=utf-8"
    assert "comicarr-shelf.csv" in exported.headers["content-disposition"]
    lines = exported.text.splitlines()
    assert lines[0] == "Series,Item,Variant,Grade,Paid,Storage,Notes,Added"
    assert lines[1].startswith("Paper Tigers,Vol. 2,,,,,,")
    assert lines[2].startswith("Starfall Saga,#64 · Chapter Sixty-Four,'=HYPERLINK(1),,60.05,Long box 03,,")


def test_every_route_requires_a_session():
    assert [dependency.dependency for dependency in router.dependencies] == [require_session]
