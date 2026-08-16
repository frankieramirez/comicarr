#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""The SearchProvider record and the legacy INI codec behind it."""

import pytest

from comicarr.app.search.provider_config import (
    SearchProvider,
    canonical_provider_boolean,
    join_newznab_category_field,
    normalize_category_list,
    parse_provider_extras,
    provider_enabled,
    providers_from_config,
    serialize_provider_extras,
    split_newznab_category_field,
)

NEWZNAB_ENTRY = ("nzb.su", "https://api.nzb.su", "1", "apikey123", "1#7030#7020", "1", 3)
TORZNAB_ENTRY = ("prowlarr", "https://prowlarr.local/api", "0", "torkey", "8020#7030", "1", 4)


class TestCodecRoundTrip:
    def test_serialize_then_parse_is_identity_for_canonical_entries(self):
        entries = [NEWZNAB_ENTRY, ("Backup", "https://b.example", "0", "", "1", "0", 9)]
        stored = serialize_provider_extras(entries)
        reparsed = parse_provider_extras(stored)
        assert reparsed == [tuple(str(field) for field in entry) for entry in entries]

    def test_parse_canonicalises_every_boolean_spelling(self):
        entry = ("n", "https://h", "True", "key", "1#7030", "yes", 1)
        (parsed,) = parse_provider_extras([entry])
        assert parsed[2] == "1"
        assert parsed[5] == "1"

    def test_parse_rejects_ambiguous_field_counts(self):
        with pytest.raises(ValueError):
            parse_provider_extras("just, six, fields, of, nonsense, text")

    def test_legacy_six_field_entries_survive(self):
        (parsed,) = parse_provider_extras([("n", "https://h", "1", "key", "7030", "1")])
        assert len(parsed) == 6


class TestBooleanConvergence:
    @pytest.mark.parametrize("spelling", ["1", "true", "True", " YES ", "on"])
    def test_every_true_spelling_reads_enabled(self, spelling):
        assert provider_enabled(("n", "h", "1", "k", "7030", spelling)) is True
        assert canonical_provider_boolean(spelling) == "1"

    @pytest.mark.parametrize("spelling", ["0", "false", "no", "off", "", "garbage"])
    def test_every_other_spelling_reads_disabled(self, spelling):
        assert provider_enabled(("n", "h", "1", "k", "7030", spelling)) is False
        assert canonical_provider_boolean(spelling) == "0"

    def test_short_or_malformed_entries_read_disabled(self):
        assert provider_enabled(("n", "h")) is False
        assert provider_enabled(None) is False


class TestNewznabCategoryField:
    def test_split_separates_uid_from_categories(self):
        assert split_newznab_category_field("1#7030#7020") == ("1", "7030,7020")

    def test_bare_value_is_a_uid_with_no_categories(self):
        assert split_newznab_category_field("7030") == ("7030", "")

    def test_join_defaults_the_uid_and_drops_a_trailing_hash(self):
        assert join_newznab_category_field(None, "7030, 7020") == "1#7030#7020"
        assert join_newznab_category_field("5", "") == "5"

    def test_normalize_strips_padding_and_blanks(self):
        assert normalize_category_list("7030, 7020, ,") == ["7030", "7020"]


class TestSearchProviderRecord:
    def test_newznab_record_unpacks_uid_and_categories(self):
        provider = SearchProvider.from_entry("newznab", NEWZNAB_ENTRY)
        assert provider.rss_uid == "1"
        assert provider.categories == ("7030", "7020")
        assert provider.verify is True
        assert provider.enabled is True
        assert provider.id == 3

    def test_torznab_record_never_carries_an_rss_uid(self):
        provider = SearchProvider.from_entry("torznab", TORZNAB_ENTRY)
        assert provider.rss_uid is None
        assert provider.categories == ("8020", "7030")
        assert provider.verify is False

    def test_record_round_trips_to_the_exact_legacy_tuple(self):
        for kind, entry in (("newznab", NEWZNAB_ENTRY), ("torznab", TORZNAB_ENTRY)):
            assert SearchProvider.from_entry(kind, entry).to_entry() == entry

    def test_legacy_six_field_entry_round_trips_without_an_id(self):
        entry = ("n", "https://h", "1", "key", "7030", "0")
        provider = SearchProvider.from_entry("newznab", entry)
        assert provider.id is None
        assert provider.to_entry() == entry

    def test_unknown_kind_is_rejected(self):
        with pytest.raises(ValueError):
            SearchProvider.from_entry("prowlarr", NEWZNAB_ENTRY)

    def test_malformed_entry_is_rejected(self):
        with pytest.raises(ValueError):
            SearchProvider.from_entry("newznab", ("only", "four", "fields", "here"))


class TestProvidersFromConfig:
    def test_reads_each_kind_from_its_config_attribute(self):
        class Config:
            EXTRA_NEWZNABS = [NEWZNAB_ENTRY]
            EXTRA_TORZNABS = [TORZNAB_ENTRY]

        newznabs = providers_from_config(Config(), "newznab")
        torznabs = providers_from_config(Config(), "torznab")
        assert [provider.name for provider in newznabs] == ["nzb.su"]
        assert [provider.name for provider in torznabs] == ["prowlarr"]

    def test_skips_malformed_rows_instead_of_raising(self):
        class Config:
            EXTRA_NEWZNABS = [("too", "short"), NEWZNAB_ENTRY]
            EXTRA_TORZNABS = None

        assert [provider.name for provider in providers_from_config(Config(), "newznab")] == ["nzb.su"]
        assert providers_from_config(Config(), "torznab") == []
