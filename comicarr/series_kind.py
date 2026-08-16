#  Copyright (C) 2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Deep module answering which provider owns a Series and where its chapters come from.

Series identity is encoded two ways that must be read together:

  * the ``ComicID`` prefix (``md-`` MangaDex, ``mal-`` MyAnimeList, otherwise
    ComicVine), which says who issued the id, and
  * the ``ContentType`` column, which says whether the Series is manga at all.

They can disagree. A manga row added before the provider prefixes existed
carries ``ContentType == 'manga'`` with an unprefixed ComicID, so a caller that
consults only the prefix will treat it as a comic. Reconciling the two is what
:func:`is_manga` is for; every caller should ask it rather than testing either
signal directly.

The load-bearing invariant is that **MyAnimeList supplies metadata but MangaDex
always supplies chapters**. A MAL-sourced Series therefore fetches chapters
against the MangaDex uuid recorded in its ``MangaDexID`` column, not against its
own ComicID. :func:`chapter_source_id` is the only place that rule is written
down.

This module imports nothing from Comicarr so that it can be imported from both
the legacy business modules and ``comicarr.app`` without cycles.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum


class SeriesProvider(str, Enum):
    """Who issued a Series id."""

    COMICVINE = "comicvine"
    MANGADEX = "mangadex"
    MYANIMELIST = "myanimelist"


#: Providers whose Series are manga. ComicVine-issued ids may *also* be manga
#: (see :func:`is_manga`) — membership here is about the id, not the content.
MANGA_PROVIDERS = frozenset({SeriesProvider.MANGADEX, SeriesProvider.MYANIMELIST})

_PROVIDER_PREFIXES: dict[SeriesProvider, str] = {
    SeriesProvider.MANGADEX: "md-",
    SeriesProvider.MYANIMELIST: "mal-",
}

_MANGA_CONTENT_TYPE = "manga"


def _series_id_of(series: str | Mapping | None) -> str:
    """Accept either a bare Series id or a Series row and return the id."""
    if series is None:
        return ""
    if isinstance(series, Mapping):
        return str(series.get("ComicID") or "")
    return str(series)


def provider_of(series: str | Mapping | None) -> SeriesProvider:
    """Return the provider that issued this Series id.

    Accepts a bare id or a Series row. Unprefixed and unknown ids are
    ComicVine — including legacy manga rows, which is why callers asking
    "is this manga?" must use :func:`is_manga` instead.
    """
    series_id = _series_id_of(series)
    for provider, prefix in _PROVIDER_PREFIXES.items():
        if series_id.startswith(prefix):
            return provider
    return SeriesProvider.COMICVINE


def is_manga(series: str | Mapping | None) -> bool:
    """Return whether this Series is manga, reconciling prefix and ContentType.

    A stored ``ContentType`` is authoritative when a row is available. Provider
    identity is only the fallback for a bare id or a legacy row whose field is
    absent/null. This lets an operator classify any provider's Series while
    retaining prefix inference for old data.
    """
    if isinstance(series, Mapping):
        content_type = series.get("ContentType")
        if content_type is not None:
            return str(content_type).strip().casefold() == _MANGA_CONTENT_TYPE
    return provider_of(series) in MANGA_PROVIDERS


def chapter_source_id(series: str | Mapping | None) -> str | None:
    """Return the MangaDex uuid to fetch this Series' chapters against.

    MangaDex-issued Series carry the uuid in the ComicID itself. MyAnimeList
    Series keep it in ``MangaDexID`` — MAL supplies metadata, MangaDex always
    supplies chapters — so a bare ``mal-`` id cannot answer this and returns
    None, as does a MAL Series whose uuid has not been resolved yet.

    Returns a raw uuid with no prefix. ComicVine Series return None.
    """
    provider = provider_of(series)
    if provider is SeriesProvider.MANGADEX:
        return strip_prefix(_series_id_of(series)) or None
    if provider is SeriesProvider.MYANIMELIST:
        if not isinstance(series, Mapping):
            return None
        return strip_prefix(str(series.get("MangaDexID") or "")) or None
    return None


def strip_prefix(series_id: str | None) -> str:
    """Return a Series id with any provider prefix removed."""
    if not series_id:
        return ""
    series_id = str(series_id)
    for prefix in _PROVIDER_PREFIXES.values():
        if series_id.startswith(prefix):
            return series_id[len(prefix) :]
    return series_id


def add_prefix(raw_id: str | None, provider: SeriesProvider) -> str:
    """Return a Series id carrying ``provider``'s prefix, adding it if absent.

    An id that already names a provider is returned untouched, so this can
    never relabel one provider's id as another's.
    """
    if not raw_id:
        return ""
    raw_id = str(raw_id)
    if provider_of(raw_id) is not SeriesProvider.COMICVINE:
        return raw_id
    prefix = _PROVIDER_PREFIXES.get(provider)
    if prefix is None:
        return raw_id
    return "%s%s" % (prefix, raw_id)


_PROVIDER_PAGE = {
    SeriesProvider.COMICVINE: (
        "ComicVine",
        "https://comicvine.gamespot.com/volume/4050-{id}/",
    ),
    SeriesProvider.MANGADEX: ("MangaDex", "https://mangadex.org/title/{id}"),
    SeriesProvider.MYANIMELIST: (
        "MyAnimeList",
        "https://myanimelist.net/manga/{id}",
    ),
}

_COMICVINE_VOLUME_PREFIX = "4050-"


def _catalog_id(series_id: str, provider: SeriesProvider) -> str:
    """Native id for a catalog URL — ComicVine volume ids must not keep 4050-."""
    if provider is SeriesProvider.COMICVINE and series_id.startswith(_COMICVINE_VOLUME_PREFIX):
        return series_id[len(_COMICVINE_VOLUME_PREFIX) :]
    return series_id


def provider_page_links(series: str | Mapping | None) -> list[dict[str, str]]:
    """Return outbound catalog links for this Series.

    Always includes the issuing provider when a native id is present. A
    MyAnimeList Series also includes its MangaDex chapter source when
    ``MangaDexID`` is set — MAL is metadata, MangaDex is chapters.
    """
    links: list[dict[str, str]] = []
    native_id = strip_prefix(_series_id_of(series))
    if native_id:
        provider = provider_of(series)
        label, template = _PROVIDER_PAGE[provider]
        links.append(
            {
                "provider": provider.value,
                "label": label,
                "url": template.format(id=_catalog_id(native_id, provider)),
            }
        )
    if provider_of(series) is SeriesProvider.MYANIMELIST:
        mangadex_id = chapter_source_id(series)
        if mangadex_id:
            label, template = _PROVIDER_PAGE[SeriesProvider.MANGADEX]
            links.append(
                {
                    "provider": SeriesProvider.MANGADEX.value,
                    "label": label,
                    "url": template.format(id=mangadex_id),
                }
            )
    return links
