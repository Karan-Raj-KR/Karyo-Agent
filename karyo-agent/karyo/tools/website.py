"""Website health-check tool — stub implementation."""
from __future__ import annotations

import json
from typing import Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from karyo.cache.store import get_store
from karyo.models.schemas import WebsiteHealth


class WebsiteInput(BaseModel):
    url: str = Field(description="URL of the website to check")


# Stub responses keyed by URL pattern
_STUB_RESPONSES: dict[str, WebsiteHealth] = {
    "smiledentalclinic.in": WebsiteHealth(
        status="slow",
        response_time_ms=4200,
        has_ssl=False,
        last_modified="2022-03-15",
        mobile_meta_tag=False,
    ),
    "cityortho.com": WebsiteHealth(
        status="alive",
        response_time_ms=780,
        has_ssl=True,
        last_modified="2024-11-01",
        mobile_meta_tag=True,
    ),
}
_DEFAULT_HEALTH = WebsiteHealth(status="none", response_time_ms=None, has_ssl=None)


def check_website(url: str) -> WebsiteHealth:
    """Cached website health check (stub)."""
    store = get_store()
    key = store.make_key("website", url)
    cached = store.get(key)
    if cached is not None:
        return WebsiteHealth(**cached)

    # Stub: pattern match on known domains
    result = _DEFAULT_HEALTH
    for domain, health in _STUB_RESPONSES.items():
        if domain in url:
            result = health
            break

    store.set(key, result.model_dump())
    return result


class WebsiteCheckTool(BaseTool):
    name: str = "website_health_check"
    description: str = (
        "Check the health of a business website: response time, SSL status, "
        "last-modified header, and mobile meta tag presence."
    )
    args_schema: Type[BaseModel] = WebsiteInput

    def _run(self, url: str) -> str:
        health = check_website(url)
        return json.dumps(health.model_dump(), indent=2)
