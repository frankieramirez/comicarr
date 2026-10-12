#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mokkari.exceptions import ApiError
from requests import Response
from requests.exceptions import HTTPError

import comicarr
from comicarr import mb
from comicarr.app.search.service import find_comic


@pytest.fixture
def providers(monkeypatch):
    config = SimpleNamespace(COMICVINE_API="mock-key", CV_VERIFY=True, USE_METRON_SEARCH=True)
    monkeypatch.setattr(comicarr, "CONFIG", config)
    monkeypatch.setattr(comicarr, "CVURL", "https://comicvine.gamespot.com/api/")
    monkeypatch.setattr(comicarr, "CV_RATE_LIMITER", MagicMock())
    session = MagicMock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = {
        "status_code": 1,
        "results": {
            "id": 12345,
            "name": "X-Men '97",
            "start_year": "2024",
            "publisher": {"name": "Marvel"},
            "count_of_issues": 4,
        },
    }
    monkeypatch.setattr(comicarr, "CV_SESSION", session)
    metron = MagicMock()
    metron.series.return_value = SimpleNamespace(
        id=99,
        name="X-Men '97",
        year_began=2024,
        publisher=SimpleNamespace(name="Marvel"),
        issue_count=4,
        cv_id=12345,
    )
    monkeypatch.setattr(comicarr, "METRON_API", metron)
    library = {}
    monkeypatch.setattr(mb, "listLibrary", lambda: library)
    name_search = MagicMock(return_value={"results": []})
    monkeypatch.setattr(mb, "findComic", name_search)
    return SimpleNamespace(config=config, session=session, metron=metron, library=library, name_search=name_search)


@pytest.mark.parametrize(
    "query",
    [
        "4050-12345",
        " 4050-12345 ",
        "https://comicvine.gamespot.com/x-men-97/4050-12345/",
        "http://www.comicvine.gamespot.com/4050-12345/?ref=share#details",
    ],
)
def test_comicvine_identifier_returns_only_requested_volume(providers, query):
    result = find_comic(providers, query)
    assert len(result["results"]) == 1
    candidate = result["results"][0]
    assert candidate["comicid"] == "12345"
    assert candidate["name"] == "X-Men '97"
    assert candidate["comicyear"] == "2024"
    assert candidate["publisher"] == "Marvel"
    assert candidate["count_of_issues"] == 4
    assert candidate["metadata_source"] == "comicvine"
    assert candidate["in_library"] is False
    providers.name_search.assert_not_called()
    providers.metron.series.assert_not_called()
    assert providers.session.get.call_args.args[0] == "https://comicvine.gamespot.com/api/volume/4050-12345/"
    assert providers.session.get.call_args.kwargs["params"]["api_key"] == "mock-key"


@pytest.mark.parametrize("query", ["https://metron.cloud/series/99/", "https://www.metron.cloud/series/99?ref=share"])
def test_metron_url_preserves_provider_identity(providers, query):
    providers.library["12345"] = "Active"
    candidate = find_comic(providers, query)["results"][0]
    assert candidate["comicid"] == "metron-99"
    assert candidate["cv_comicid"] == "12345"
    assert candidate["metadata_source"] == "metron"
    assert candidate["name"] == "X-Men '97"
    assert candidate["comicyear"] == "2024"
    assert candidate["publisher"] == "Marvel"
    assert candidate["in_library"] is True
    providers.metron.series.assert_called_once_with(99)
    providers.session.get.assert_not_called()
    providers.name_search.assert_not_called()


@pytest.mark.parametrize(
    "query",
    [
        "12345",
        "X-Men '97",
        "4050-12345 extra",
        "https://comicvine.gamespot.com.evil.test/title/4050-12345/",
        "https://evil.test/title/4050-12345/",
        "https://metron.cloud.evil.test/series/99/",
        "https://metron.cloud/issue/99/",
        "https://comicvine.gamespot.com/title/4000-12345/",
        "https://evil.test@metron.cloud/series/99/",
        "https://metron.cloud:9999/series/99/",
        "file://metron.cloud/series/99/",
        "https://metron.cloud/series/99/extra",
        "https://metron.cloud/series/%39%39/",
        "https://[broken/series/99/",
    ],
)
def test_text_numbers_and_unsupported_urls_remain_text_searches(providers, query):
    assert find_comic(providers, query) == {"results": []}
    providers.name_search.assert_called_once()
    assert providers.name_search.call_args.args[0] == query
    providers.session.get.assert_not_called()
    providers.metron.series.assert_not_called()


@pytest.mark.parametrize("not_found", ["http", "provider", "empty"])
def test_missing_comicvine_volume_has_no_fallback(providers, not_found):
    response = providers.session.get.return_value
    if not_found == "http":
        response.status_code = 404
    elif not_found == "provider":
        response.json.return_value = {"status_code": 101}
    else:
        response.json.return_value = {"status_code": 1, "results": None}
    assert find_comic(providers, "4050-12345")["results"] == []
    providers.name_search.assert_not_called()
    providers.metron.series.assert_not_called()


@pytest.mark.parametrize("error", [ApiError("Not found."), ApiError("No Series matches the given query.")])
def test_missing_metron_series_has_no_fallback(providers, error):
    providers.metron.series.side_effect = error
    assert find_comic(providers, "https://metron.cloud/series/99/")["results"] == []
    providers.name_search.assert_not_called()
    providers.session.get.assert_not_called()


@pytest.mark.parametrize("provider", ["comicvine", "metron"])
def test_provider_configuration_failure_is_explicit(providers, provider):
    query = "4050-12345" if provider == "comicvine" else "https://metron.cloud/series/99/"
    if provider == "comicvine":
        providers.config.COMICVINE_API = None
    else:
        providers.config.USE_METRON_SEARCH = False
    result = find_comic(providers, query)
    assert provider.lower() in result["error"].lower()
    providers.name_search.assert_not_called()
    providers.session.get.assert_not_called()
    providers.metron.series.assert_not_called()


@pytest.mark.parametrize("provider", ["comicvine", "metron"])
def test_provider_failure_never_falls_back_or_leaks_exception(providers, provider):
    query = "4050-12345" if provider == "comicvine" else "https://metron.cloud/series/99/"
    call = providers.session.get if provider == "comicvine" else providers.metron.series
    call.side_effect = RuntimeError("secret credentials")
    result = find_comic(providers, query)
    assert provider.lower() in result["error"].lower()
    assert "secret" not in result["error"]
    providers.name_search.assert_not_called()


@pytest.mark.parametrize("provider", ["comicvine", "metron"])
def test_wrong_provider_volume_is_rejected(providers, provider):
    if provider == "comicvine":
        providers.session.get.return_value.json.return_value["results"]["id"] = 54321
        query = "4050-12345"
    else:
        providers.metron.series.return_value.id = 100
        query = "https://metron.cloud/series/99/"
    assert "different" in find_comic(providers, query)["error"]
    providers.name_search.assert_not_called()


def test_comicvine_library_membership_uses_id_not_title(providers):
    providers.library["name:x-men '97:2024"] = "Active"
    assert find_comic(providers, "4050-12345")["results"][0]["in_library"] is False
    providers.library["12345"] = "Active"
    assert find_comic(providers, "4050-12345")["results"][0]["in_library"] is True


def test_invalid_comicvine_key_returns_provider_error(providers):
    providers.session.get.return_value.json.return_value = {"status_code": 100, "error": "Invalid API Key"}
    assert "ComicVine" in find_comic(providers, "4050-12345")["error"]
    providers.name_search.assert_not_called()


@pytest.mark.parametrize("status", [404, 401, 403, 503])
def test_metron_wrapped_http_errors_preserve_not_found_and_failures(providers, status):
    response = Response()
    response.status_code = status
    error = ApiError("HTTP error: provider response")
    error.__cause__ = HTTPError(response=response)
    providers.metron.series.side_effect = error
    result = find_comic(providers, "https://metron.cloud/series/99/")
    if status == 404:
        assert result["results"] == []
    else:
        assert "Metron" in result["error"]
    providers.name_search.assert_not_called()


def test_search_endpoint_preserves_empty_and_provider_error_results(providers):
    import json

    from comicarr.app.search.router import search_comics

    providers.session.get.return_value.status_code = 404
    assert search_comics({"name": "4050-12345"}, ctx=providers)["results"] == []
    providers.config.USE_METRON_SEARCH = False
    result = search_comics({"name": "https://metron.cloud/series/99/"}, ctx=providers)
    assert result.status_code == 400
    assert json.loads(result.body) == {"detail": "Metron integration is not configured"}


@pytest.mark.parametrize("query", ["4050-12345", "https://metron.cloud/series/99/"])
@pytest.mark.parametrize("offset,returned", [(0, 1), (1, 0), (20, 0)])
def test_exact_lookup_endpoint_reports_pagination_and_honors_offset(providers, query, offset, returned):
    from comicarr.app.search.router import search_comics

    result = search_comics({"name": query, "limit": 20, "offset": offset}, ctx=providers)
    assert len(result["results"]) == returned
    assert result["pagination"] == {"total": 1, "limit": 20, "offset": offset, "returned": returned}


def test_missing_exact_lookup_has_zero_total_and_returned(providers):
    from comicarr.app.search.router import search_comics

    providers.session.get.return_value.status_code = 404
    result = search_comics({"name": "4050-12345", "limit": 20, "offset": 0}, ctx=providers)
    assert result == {"results": [], "pagination": {"total": 0, "limit": 20, "offset": 0, "returned": 0}}


@pytest.mark.parametrize("parameters", [{"limit": -1}, {"offset": -1}])
def test_exact_lookup_rejects_negative_pagination_before_provider_calls(providers, parameters):
    assert find_comic(providers, "4050-12345", **parameters) == {"error": "Invalid pagination parameters"}
    providers.session.get.assert_not_called()
    providers.metron.series.assert_not_called()
