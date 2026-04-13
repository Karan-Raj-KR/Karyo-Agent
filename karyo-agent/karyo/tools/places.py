"""Google Places tool — returns hardcoded stub data (real API call wired later)."""
from __future__ import annotations

import json
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from karyo.cache.store import get_store


class PlacesInput(BaseModel):
    city: str = Field(description="City or neighbourhood to search in")
    category: str = Field(description="Category / type of business to search for")


# ---------------------------------------------------------------------------
# Hardcoded stub data — replace _fetch() body with real Google Places call
# ---------------------------------------------------------------------------
_STUB_BUSINESSES = [
    {
        "name": "Smile Dental Clinic",
        "place_id": "ChIJstub001",
        "address": "12, MG Road, {city}",
        "phone": "+91 80 2345 6789",
        "website": "http://smiledentalclinic.in",
        "google_rating": 4.2,
        "review_count": 87,
    },
    {
        "name": "Indira Dental Care",
        "place_id": "ChIJstub002",
        "address": "45, 100 Feet Road, {city}",
        "phone": "+91 80 3456 7890",
        "website": None,
        "google_rating": 3.8,
        "review_count": 34,
    },
    {
        "name": "City Orthodontics",
        "place_id": "ChIJstub003",
        "address": "78, Brigade Road, {city}",
        "phone": "+91 80 4567 8901",
        "website": "https://cityortho.com",
        "google_rating": 4.6,
        "review_count": 212,
    },
]


def fetch_places(city: str, category: str) -> list[dict[str, Any]]:
    """Cached places lookup (stub)."""
    store = get_store()
    key = store.make_key("places", city, category)
    cached = store.get(key)
    if cached is not None:
        return cached

    # Stub: interpolate city into address
    result = [
        {**b, "address": b["address"].format(city=city)}
        for b in _STUB_BUSINESSES
    ]
    store.set(key, result)
    return result


class PlacesTool(BaseTool):
    name: str = "google_places_search"
    description: str = (
        "Search for local businesses using Google Places API. "
        "Returns business name, address, phone, website, rating, and review count."
    )
    args_schema: Type[BaseModel] = PlacesInput

    def _run(self, city: str, category: str) -> str:
        businesses = fetch_places(city, category)
        return json.dumps(businesses, indent=2)
