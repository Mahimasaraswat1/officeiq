"""Shared response envelopes (PRD B.6: consistent error schema, versioned API)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorPayload(BaseModel):
    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human-readable description")
    details: dict | list | None = None


class ErrorResponse(BaseModel):
    """Every non-2xx response from the API uses this shape."""

    status: int
    error: ErrorPayload


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class Message(BaseModel):
    message: str
