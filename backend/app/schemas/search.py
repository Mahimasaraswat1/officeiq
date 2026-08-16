"""Global search contracts (PRD A.9)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SearchKind = Literal["employee", "document", "task", "knowledge"]


class SearchHit(BaseModel):
    kind: SearchKind
    id: str
    title: str
    subtitle: str | None = None
    badge: str | None = Field(
        default=None, description="Status word the UI can render as a chip"
    )
    link: str = Field(description="Frontend route that opens this result")


class SearchGroup(BaseModel):
    kind: SearchKind
    label: str
    total: int = Field(description="Matches found, which may exceed len(items)")
    items: list[SearchHit]


class SearchResults(BaseModel):
    query: str
    total: int
    groups: list[SearchGroup]
    limit_per_group: int
