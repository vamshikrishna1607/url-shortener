from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, Field


class ShortenRequest(BaseModel):
    url: AnyHttpUrl = Field(..., description="The URL to shorten (must be http/https).")


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    original_url: str


class StatsResponse(BaseModel):
    short_code: str
    original_url: str
    clicks: int
