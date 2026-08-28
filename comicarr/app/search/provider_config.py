#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The Search provider record and the legacy INI codec that stores it.

A configured Newznab or Torznab Search provider is persisted as a flat
positional tuple inside one comma-joined INI option (``extra_newznabs`` /
``extra_torznabs``).  Every fact about that encoding lives here and only
here: the legal widths, which fields are booleans and how they must be
spelled, which field is the Fernet-encrypted credential, and how field 4
packs ``rss_uid#categories`` for Newznab but a bare category list for
Torznab.  Callers work with :class:`SearchProvider` and ask by name;
``config.py`` calls the codec at its load/store choke points and is the
only module that still needs the raw tuple shape.
"""

from __future__ import annotations

from dataclasses import dataclass

PROVIDER_EXTRA_FIELDS = ("EXTRA_NEWZNABS", "EXTRA_TORZNABS")
PROVIDER_EXTRA_WIDTHS = (6, 7)
PROVIDER_CREDENTIAL_INDEX = 3
_PROVIDER_BOOLEAN_VALUES = {"0", "1", "false", "true", "no", "yes", "off", "on"}
_PROVIDER_BOOLEAN_TRUE = {"1", "true", "yes", "on"}
PROVIDER_BOOLEAN_INDEXES = (2, 5)

DEFAULT_NEWZNAB_RSS_UID = "1"


def canonical_provider_boolean(value):
    """Return a provider boolean field as the only spelling every reader agrees on.

    `_PROVIDER_BOOLEAN_VALUES` accepts eight spellings, but the consumers do
    not. `search.py` and `rsscheck.py` read verify as `bool(int(field))`, which
    raises `ValueError` on `"True"`; the enabled filters in `search.py` compare
    against the literal `"1"` while `health.py` and the providers API accept
    `true`/`yes`/`on`. So an entry stored as `True` was reported enabled by the
    Acquisition tab and skipped by the searcher -- and one stored with a
    non-numeric verify took the search down. Both fields are normalised here,
    at the single boundary every reader and writer passes through, so tolerance
    at the edge cannot become disagreement in the middle.
    """
    return "1" if str(value).strip().lower() in _PROVIDER_BOOLEAN_TRUE else "0"


def provider_boolean(value) -> bool:
    """Read a provider boolean field, tolerating every historical spelling."""
    return str(value).strip().lower() in _PROVIDER_BOOLEAN_TRUE


def provider_enabled(entry) -> bool:
    """The one enabled test for a raw provider tuple."""
    try:
        return provider_boolean(entry[5])
    except (IndexError, TypeError):
        return False


def _provider_entry_is_structurally_valid(entry):
    """Distinguish historical six- and seven-field provider records safely."""
    if len(entry) not in PROVIDER_EXTRA_WIDTHS:
        return False
    if str(entry[2]).strip().lower() not in _PROVIDER_BOOLEAN_VALUES:
        return False
    if str(entry[5]).strip().lower() not in _PROVIDER_BOOLEAN_VALUES:
        return False
    if len(entry) == 7:
        try:
            int(entry[6])
        except (TypeError, ValueError):
            return False
    return True


def parse_provider_extras(value, config_version=15):
    """Parse provider extras without assuming one historical tuple width."""
    if value in (None, "", "None"):
        return []

    if isinstance(value, (list, tuple)):
        entries = value
    elif isinstance(value, str):
        parts = value.split(", ")
        candidates = []
        for width in PROVIDER_EXTRA_WIDTHS:
            if len(parts) % width:
                continue
            candidate = [parts[index : index + width] for index in range(0, len(parts), width)]
            if all(_provider_entry_is_structurally_valid(entry) for entry in candidate):
                candidates.append(candidate)
        if len(candidates) != 1:
            raise ValueError("Provider configuration has an invalid field count")
        entries = candidates[0]
    else:
        raise ValueError("Provider configuration must be a list of entries")

    parsed = []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or not _provider_entry_is_structurally_valid(entry):
            raise ValueError("Provider entries must contain six or seven fields")
        values = list(entry)
        for index in PROVIDER_BOOLEAN_INDEXES:
            values[index] = canonical_provider_boolean(values[index])
        parsed.append(tuple(values))
    return parsed


def serialize_provider_extras(entries):
    """Serialize validated provider entries using the legacy flat INI format."""
    flattened = []
    for entry in parse_provider_extras(entries):
        for index, value in enumerate(entry):
            field = "" if value is None else str(value)
            if index == 4:
                field = field.replace(",", "#")
            elif ", " in field:
                raise ValueError("Provider fields cannot contain the INI delimiter")
            flattened.append(field)
    return ", ".join(flattened)


def normalize_category_list(value, separator=","):
    """Return the category ids in ``value`` with blanks and padding removed.

    `7030, 7020` typed into Settings used to be stored with the space intact
    and would have reached the indexer as `cat=7030, 7020`. It never showed
    because the categories were not reaching the searcher at all; now that they
    are, the field has to survive the way operators actually type a list.
    """
    return [part.strip() for part in str(value or "").split(separator) if part.strip()]


def split_newznab_category_field(value):
    """Split a Newznab category field into its RSS uid and its category list.

    Field 5 of a Newznab record is ``uid#categories``: the uid is the ``i=``
    parameter of the indexer's RSS URL, and everything after the first ``#`` is
    the category list. A value with no ``#`` is a uid on its own, which is why
    a bare ``7030`` typed into the Settings Categories box was stored as a uid
    and searched nothing -- the categories the operator asked for were dropped
    on the floor with no error. Returned as ``(uid, categories)`` with the
    category separator normalised to a comma for display.

    Torznab records have no uid; field 5 there is the category list alone.
    """
    uid, separator, categories = str(value or "").partition("#")
    if not separator:
        return uid.strip(), ""
    return uid.strip(), ",".join(normalize_category_list(categories, "#"))


def join_newznab_category_field(uid, categories):
    """Rebuild the stored ``uid#categories`` field from its two halves."""
    uid = str(uid or "").strip() or DEFAULT_NEWZNAB_RSS_UID
    categories = "#".join(normalize_category_list(categories))
    return "%s#%s" % (uid, categories) if categories else uid


@dataclass(frozen=True)
class SearchProvider:
    """One configured Newznab or Torznab Search provider, fields by name.

    ``rss_uid`` is a Newznab concept only -- Torznab stores a bare category
    list in the same packed field, so a Torznab record always carries
    ``rss_uid=None``.  ``id`` is ``None`` only for legacy six-field rows that
    have never been persisted since ids were introduced.
    """

    kind: str
    name: str
    host: str
    verify: bool
    api_key: str
    categories: tuple[str, ...]
    enabled: bool
    rss_uid: str | None = None
    id: int | None = None

    @classmethod
    def from_entry(cls, kind, entry) -> "SearchProvider":
        """Build a record from one raw legacy tuple (six or seven fields)."""
        if kind not in ("newznab", "torznab"):
            raise ValueError("Unknown search provider kind: %s" % kind)
        if not isinstance(entry, (list, tuple)) or not _provider_entry_is_structurally_valid(entry):
            raise ValueError("Provider entries must contain six or seven fields")
        if kind == "newznab":
            rss_uid, categories = split_newznab_category_field(entry[4])
            category_ids = tuple(normalize_category_list(categories))
        else:
            rss_uid = None
            category_ids = tuple(normalize_category_list(entry[4], "#"))
        provider_id = None
        if len(entry) == 7:
            provider_id = int(entry[6])
        return cls(
            kind=kind,
            name=str(entry[0] or ""),
            host=str(entry[1] or ""),
            verify=provider_boolean(entry[2]),
            api_key="" if entry[3] in (None, "None") else str(entry[3]),
            categories=category_ids,
            enabled=provider_boolean(entry[5]),
            rss_uid=rss_uid,
            id=provider_id,
        )

    def to_entry(self) -> tuple:
        """Render the exact legacy tuple the INI codec and search path consume."""
        if self.kind == "newznab":
            category_field = join_newznab_category_field(self.rss_uid, ",".join(self.categories))
        else:
            category_field = "#".join(self.categories)
        entry = [
            self.name,
            self.host,
            canonical_provider_boolean(self.verify),
            self.api_key,
            category_field,
            canonical_provider_boolean(self.enabled),
        ]
        if self.id is not None:
            entry.append(self.id)
        return tuple(entry)


def providers_from_config(config, kind) -> list[SearchProvider]:
    """Read the configured Search providers of one kind as records."""
    attr_name = "EXTRA_NEWZNABS" if kind == "newznab" else "EXTRA_TORZNABS"
    records = []
    for entry in getattr(config, attr_name, None) or []:
        try:
            records.append(SearchProvider.from_entry(kind, entry))
        except (TypeError, ValueError):
            continue
    return records
