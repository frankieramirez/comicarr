#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Pydantic v2 models for structured LLM output.

Each schema represents a specific AI feature's expected response
format. Used with structured.py to validate JSON from the LLM.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel


class FilenameParse(BaseModel):
    series_name: str
    issue_number: str
    year: Optional[str] = None
    volume: Optional[str] = None


class MetadataEnrichment(BaseModel):
    fields: Dict[str, str]


class SearchExpansion(BaseModel):
    queries: List[str]


class QueryPattern(BaseModel):
    pattern_id: str
    parameters: Dict[str, str]


class ArcIssue(BaseModel):
    series_name: str
    issue_number: str
    title: Optional[str] = None
    reading_order_position: int


class ReadingOrder(BaseModel):
    issues: List[ArcIssue]


class PullSuggestion(BaseModel):
    comic_name: str
    publisher: str
    reason: str
    resolved_comic_id: Optional[str] = None


class PullSuggestions(BaseModel):
    suggestions: List[PullSuggestion]


class ReconciliationChoice(BaseModel):
    choices: Dict[str, str]


class InsightsResponse(BaseModel):
    insights: str
    generated_at: str
