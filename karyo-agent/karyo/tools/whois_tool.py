"""WHOIS domain-age tool — stub implementation."""
from __future__ import annotations

import json
from typing import Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from karyo.cache.store import get_store


class WhoisInput(BaseModel):
    domain: str = Field(description="Domain name to look up (e.g. example.com)")


_STUB_AGES: dict[str, float] = {
    "smiledentalclinic.in": 3.2,
    "cityortho.com": 8.7,
}


def get_domain_age(domain: str) -> Optional[float]:
    """Cached domain-age lookup (stub). Returns age in years or None."""
    store = get_store()
    key = store.make_key("whois", domain)
    cached = store.get(key)
    if cached is not None:
        return cached

    result: Optional[float] = None
    for known_domain, age in _STUB_AGES.items():
        if known_domain in domain:
            result = age
            break

    store.set(key, result)
    return result


class WhoisTool(BaseTool):
    name: str = "domain_age_lookup"
    description: str = (
        "Look up the age of a domain in years using WHOIS data. "
        "Older domains (>5 years) indicate an established business."
    )
    args_schema: Type[BaseModel] = WhoisInput

    def _run(self, domain: str) -> str:
        age = get_domain_age(domain)
        return json.dumps({"domain": domain, "age_years": age}, indent=2)
