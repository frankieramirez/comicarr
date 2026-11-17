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

import comicarr
from comicarr.app.core.security import require_session
from comicarr.app.shelf import service
from comicarr.app.shelf.router import router
from comicarr.db import get_engine, shutdown_engine
from comicarr.tables import annuals, comics, issues, metadata, physical_copies


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(comicarr, "DATA_DIR", str(tmp_path))
    shutdown_engine()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if getattr(comicarr, "LOG_LEVEL", None) is None:
        monkeypatch.setattr(comicarr, "LOG_LEVEL", 0, raising=False)
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
    return service.create_copy({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", **fields})


def test_two_covers_of_one_issue_are_two_copies():
    standard = _issue_copy(GradeService="raw", Grade="9.4", PaidCents=499, Currency="usd", Storage="Long box 03")
    virgin = _issue_copy(VariantName="1:25 virgin", GradeService="CGC", Grade=9.8, PaidCents=6000, Currency="USD")

    assert standard["CopyID"] != virgin["CopyID"]
    assert standard["State"] == "owned"
    assert standard["Currency"] == "USD"
    assert virgin["GradeService"] == "cgc"
    assert virgin["Grade"] == "9.8"
    assert standard["SeriesName"] == "Starfall Saga"
    assert standard["ItemLabel"] == "#64 · Chapter Sixty-Four"
    assert standard["CoverURL"] == "https://img.example/64.jpg"
    assert standard["Format"] == "single"
    assert service.series_shelf("100") == {
        "comic_id": "100",
        "items": {"issue:i64": {"owned": 2, "wishlist": 0}},
        "totals": {"on_shelf": 1, "copies": 2, "wishlist": 0, "paid_cents": {"USD": 6499}},
    }


def test_a_copy_never_touches_the_issue_status():
    _issue_copy()
    service.create_copy({"ComicID": "100", "ItemKind": "issue", "ItemID": "i65"})
    with get_engine().connect() as conn:
        statuses = dict(conn.execute(select(issues.c.IssueID, issues.c.Status)).all())
    assert statuses == {"i64": "Downloaded", "i65": "Wanted", "t1": "Skipped"}


def test_format_follows_the_series_type():
    assert service.create_copy({"ComicID": "200", "ItemKind": "issue", "ItemID": "t1"})["Format"] == "tpb"
    volume = service.create_copy({"ComicID": "md-1", "ItemKind": "volume", "VolumeNumber": "01"})
    assert volume["Format"] == "tankobon"
    assert volume["VolumeNumber"] == "1"
    assert volume["ItemLabel"] == "Vol. 1"
    assert service.series_shelf("md-1")["items"] == {"volume:1": {"owned": 1, "wishlist": 0}}


def test_annuals_are_their_own_item_kind():
    copy = service.create_copy({"ComicID": "100", "ItemKind": "annual", "ItemID": "a1"})
    assert copy["ItemKind"] == "annual"
    assert set(service.series_shelf("100")["items"]) == {"annual:a1"}


@pytest.mark.parametrize(
    ("body", "code", "field"),
    [
        ({"ComicID": "nope", "ItemKind": "issue", "ItemID": "i64"}, "series_not_found", None),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "missing"}, "item_not_found", None),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "t1"}, "item_not_found", None),
        ({"ComicID": "100", "ItemKind": "volume", "VolumeNumber": "1"}, "volume_needs_manga", "ItemKind"),
        ({"ComicID": "md-1", "ItemKind": "volume", "VolumeNumber": ""}, "invalid_field", "VolumeNumber"),
        ({"ComicID": "100", "ItemKind": "box", "ItemID": "i64"}, "invalid_field", "ItemKind"),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "State": "sold"}, "invalid_field", "State"),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "Grade": "11"}, "invalid_field", "Grade"),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "Grade": "NaN"}, "invalid_field", "Grade"),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "PaidCents": -1}, "invalid_field", "PaidCents"),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "PaidCents": 4.99}, "invalid_field", "PaidCents"),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "Currency": "dollars"}, "invalid_field", "Currency"),
        (
            {"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "BoughtOn": "17/09/2026"},
            "invalid_field",
            "BoughtOn",
        ),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "Barcode": "abc"}, "invalid_field", "Barcode"),
        (
            {"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "VariantImageURL": "javascript:alert(1)"},
            "invalid_field",
            "VariantImageURL",
        ),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "Notes": "x" * 4001}, "field_too_long", "Notes"),
        ({"ComicID": "100", "ItemKind": "issue", "ItemID": "i64", "Owner": "me"}, "unknown_field", "Owner"),
    ],
)
def test_bad_input_is_refused_with_a_code(body, code, field):
    with pytest.raises(service.CopyError) as caught:
        service.create_copy(body)
    assert caught.value.code == code
    assert caught.value.field == field
    with get_engine().connect() as conn:
        assert conn.execute(select(physical_copies)).first() is None


def test_a_17_digit_comic_upc_and_an_isbn_10_are_accepted():
    assert _issue_copy(Barcode="76194134182800111")["Barcode"] == "76194134182800111"
    assert _issue_copy(Barcode="080442957X")["Barcode"] == "080442957X"


def test_the_copy_outlives_its_series_and_relinks_when_it_returns():
    copy = _issue_copy(VariantName="1:25 virgin")
    with get_engine().begin() as conn:
        conn.execute(delete(issues).where(issues.c.ComicID == "100"))
        conn.execute(delete(comics).where(comics.c.ComicID == "100"))

    orphan = service.get_copy(copy["CopyID"])
    assert orphan["SeriesPresent"] is False
    assert orphan["SeriesName"] == "Starfall Saga"
    assert orphan["ItemLabel"] == "#64 · Chapter Sixty-Four"
    assert service.list_copies(query="starfall")["total"] == 1

    with get_engine().begin() as conn:
        conn.execute(insert(comics).values(ComicID="100", ComicName="Starfall Saga (2012)"))
    back = service.get_copy(copy["CopyID"])
    assert back["SeriesPresent"] is True
    assert back["SeriesName"] == "Starfall Saga (2012)"


def test_update_changes_operator_fields_but_not_the_item():
    copy = _issue_copy()
    updated = service.update_copy(copy["CopyID"], {"State": "wishlist", "Grade": "", "Storage": "  Slab shelf "})
    assert updated["State"] == "wishlist"
    assert updated["Storage"] == "Slab shelf"
    with pytest.raises(service.CopyError) as caught:
        service.update_copy(copy["CopyID"], {"ItemID": "i65"})
    assert caught.value.code == "field_not_editable"
    with pytest.raises(service.CopyError) as caught:
        service.update_copy("missing", {"Notes": "x"})
    assert caught.value.status == 404


def test_bulk_mark_promotes_a_wishlist_entry_and_skips_owned_items():
    items = [{"ItemKind": "issue", "ItemID": "i64"}, {"ItemKind": "issue", "ItemID": "i65"}]
    assert service.mark_items("100", "wishlist", items) == {"created": 2, "promoted": 0, "skipped": 0}
    assert service.mark_items("100", "wishlist", items) == {"created": 0, "promoted": 0, "skipped": 2}
    assert service.mark_items("100", "owned", items[:1]) == {"created": 0, "promoted": 1, "skipped": 0}
    assert service.mark_items("100", "owned", items) == {"created": 0, "promoted": 1, "skipped": 1}
    assert service.mark_items("100", "wishlist", items) == {"created": 0, "promoted": 0, "skipped": 2}
    assert service.series_shelf("100")["items"] == {
        "issue:i64": {"owned": 1, "wishlist": 0},
        "issue:i65": {"owned": 1, "wishlist": 0},
    }


def test_bulk_mark_is_all_or_nothing():
    items = [{"ItemKind": "issue", "ItemID": "i64"}, {"ItemKind": "issue", "ItemID": "missing"}]
    with pytest.raises(service.CopyError):
        service.mark_items("100", "owned", items)
    assert service.series_shelf("100")["items"] == {}


def test_summary_counts_owned_items_and_keeps_currencies_apart():
    _issue_copy(PaidCents=499, Currency="USD", GradeService="cgc", Grade="9.8", EstimateCents=14000)
    _issue_copy(PaidCents=300, Currency="EUR")
    service.create_copy({"ComicID": "100", "ItemKind": "issue", "ItemID": "i65", "State": "wishlist"})
    assert service.summary() == {
        "copies": 2,
        "items": 1,
        "wishlist": 1,
        "graded": 1,
        "paid_cents": {"USD": 499, "EUR": 300},
        "estimate_cents": {"USD": 14000},
        "estimated_copies": 1,
    }


def test_list_filters_and_storage_places():
    _issue_copy(Storage="Long box 03")
    _issue_copy(Storage="Slab shelf", State="wishlist")
    service.create_copy({"ComicID": "md-1", "ItemKind": "volume", "VolumeNumber": "2", "Storage": "Shelf B"})

    assert service.list_copies(comic_id="100")["total"] == 2
    assert service.list_copies(state="wishlist")["total"] == 1
    assert service.list_copies(item_kind="volume")["total"] == 1
    assert service.list_copies(storage="Long box 03")["total"] == 1
    assert service.list_copies(limit=1)["results"][0]["ComicID"] in {"100", "md-1"}
    assert set(service.storage_places()) == {"Long box 03", "Slab shelf", "Shelf B"}
    with pytest.raises(service.CopyError):
        service.list_copies(state="sold")


def test_routes_round_trip_and_return_codes(client):
    created = client.post("/api/shelf/copies", json={"ComicID": "100", "ItemKind": "issue", "ItemID": "i64"})
    assert created.status_code == 201
    copy_id = created.json()["CopyID"]

    assert client.get("/api/shelf/copies/%s" % copy_id).json()["ItemID"] == "i64"
    patched = client.patch("/api/shelf/copies/%s" % copy_id, json={"Grade": "9.6"})
    assert patched.status_code == 200 and patched.json()["Grade"] == "9.6"

    refused = client.patch("/api/shelf/copies/%s" % copy_id, json={"Grade": "eleven"})
    assert refused.status_code == 400
    assert refused.json() == {"detail": "invalid_field", "code": "invalid_field", "field": "Grade"}

    missing = client.post("/api/shelf/copies", json={"ComicID": "nope", "ItemKind": "issue", "ItemID": "x"})
    assert missing.status_code == 404 and missing.json()["code"] == "series_not_found"

    marked = client.post(
        "/api/shelf/series/100/mark", json={"State": "owned", "items": [{"ItemKind": "issue", "ItemID": "i65"}]}
    )
    assert marked.json() == {"created": 1, "promoted": 0, "skipped": 0}
    assert client.get("/api/shelf/series/100").json()["totals"]["on_shelf"] == 2
    assert client.get("/api/shelf/summary").json()["copies"] == 2
    assert client.get("/api/shelf/copies", params={"state": "owned"}).json()["total"] == 2
    assert client.get("/api/shelf/copies", params={"state": "sold"}).status_code == 400

    assert client.delete("/api/shelf/copies/%s" % copy_id).status_code == 204
    assert client.delete("/api/shelf/copies/%s" % copy_id).status_code == 404
    assert client.get("/api/shelf/copies/%s" % copy_id).status_code == 404


def test_every_route_requires_a_session():
    assert [dependency.dependency for dependency in router.dependencies] == [require_session]
