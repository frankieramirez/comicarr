#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Tests for comicarr.app.ai.schemas."""

import pytest
from pydantic import ValidationError

from comicarr.app.ai.schemas import (
    ArcIssue,
    FilenameParse,
    InsightsResponse,
    MetadataEnrichment,
    PullSuggestion,
    PullSuggestions,
    QueryPattern,
    ReadingOrder,
    ReconciliationChoice,
    SearchExpansion,
)


class TestFilenameParse:
    def test_valid_full(self):
        fp = FilenameParse(series_name="Batman", issue_number="42", year="2020", volume="3")
        assert fp.series_name == "Batman"
        assert fp.issue_number == "42"
        assert fp.year == "2020"
        assert fp.volume == "3"

    def test_valid_minimal(self):
        fp = FilenameParse(series_name="Spider-Man", issue_number="1")
        assert fp.year is None
        assert fp.volume is None

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            FilenameParse(series_name="Batman")


class TestMetadataEnrichment:
    def test_valid(self):
        me = MetadataEnrichment(fields={"genre": "Superhero", "age_rating": "T+"})
        assert me.fields["genre"] == "Superhero"

    def test_empty_fields(self):
        me = MetadataEnrichment(fields={})
        assert me.fields == {}


class TestSearchExpansion:
    def test_valid(self):
        se = SearchExpansion(queries=["batman dark knight", "batman tdk"])
        assert len(se.queries) == 2

    def test_missing_queries(self):
        with pytest.raises(ValidationError):
            SearchExpansion()


class TestQueryPattern:
    def test_valid(self):
        qp = QueryPattern(pattern_id="exact_match", parameters={"name": "Batman"})
        assert qp.pattern_id == "exact_match"


class TestArcIssue:
    def test_valid(self):
        ai = ArcIssue(
            series_name="Batman",
            issue_number="1",
            title="The Court of Owls",
            reading_order_position=1,
        )
        assert ai.title == "The Court of Owls"

    def test_without_title(self):
        ai = ArcIssue(series_name="Batman", issue_number="2", reading_order_position=2)
        assert ai.title is None


class TestReadingOrder:
    def test_valid(self):
        ro = ReadingOrder(
            issues=[
                ArcIssue(series_name="Batman", issue_number="1", reading_order_position=1),
                ArcIssue(series_name="Batman", issue_number="2", reading_order_position=2),
            ]
        )
        assert len(ro.issues) == 2


class TestPullSuggestion:
    def test_valid_with_resolved_id(self):
        ps = PullSuggestion(
            comic_name="Batman",
            publisher="DC Comics",
            reason="Popular ongoing series",
            resolved_comic_id="12345",
        )
        assert ps.resolved_comic_id == "12345"

    def test_valid_without_resolved_id(self):
        ps = PullSuggestion(
            comic_name="Batman",
            publisher="DC Comics",
            reason="Popular",
        )
        assert ps.resolved_comic_id is None


class TestPullSuggestions:
    def test_valid(self):
        ps = PullSuggestions(
            suggestions=[
                PullSuggestion(comic_name="Batman", publisher="DC", reason="Great"),
            ]
        )
        assert len(ps.suggestions) == 1


class TestReconciliationChoice:
    def test_valid(self):
        rc = ReconciliationChoice(choices={"title": "Batman #42", "year": "2020"})
        assert rc.choices["title"] == "Batman #42"


class TestInsightsResponse:
    def test_valid(self):
        ir = InsightsResponse(
            insights="Your collection is 85% DC Comics.",
            generated_at="2026-04-05T12:00:00Z",
        )
        assert "DC Comics" in ir.insights

    def test_missing_fields(self):
        with pytest.raises(ValidationError):
            InsightsResponse(insights="Some insight")
