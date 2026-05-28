"""Pydantic models for API requests/responses."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    start_datetime: datetime
    end_datetime: Optional[datetime] = None
    location: Optional[str] = None
    is_virtual: bool = False
    organiser: Optional[str] = None
    source_platform: str
    source_url: Optional[str] = None
    categories: list[str] = []
    image_url: Optional[str] = None

    @field_validator("categories", mode="before")
    @classmethod
    def parse_categories(cls, v):
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v or []


class EventResponse(EventBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RefreshResponse(BaseModel):
    status: str
    message: str
    events_scraped: int = 0


class SourceStatus(BaseModel):
    name: str
    platform: str
    last_scraped: Optional[datetime] = None
    event_count: int = 0
    enabled: bool = True


class CategoryInfo(BaseModel):
    name: str
    color: str
    keywords: list[str]