"""Real WHOIS domain-age tool with hard 10-second timeout."""
from __future__ import annotations

import concurrent.futures
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from karyo.cache.store import get_store

log = logging.getLogger(__name__)

WHOIS_TIMEOUT_S = 10   # hard wall-clock timeout — whois can hang indefinitely


def _strip_scheme(domain: str) -> str:
    """Remove http(s):// and trailing paths, return bare domain."""
    domain = domain.strip().lower()
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    # Drop path/query/port
    domain = domain.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    return domain


def _lookup_whois_blocking(domain: str) -> Optional[float]:
    """
    Perform the actual WHOIS lookup (blocking).
    Returns domain age in years as a float, or None on any failure.
    Meant to be called inside a thread with an external timeout.
    """
    try:
        import whois  # python-whois
        w = whois.whois(domain)
    except Exception as exc:
        log.debug("whois lookup failed for %s: %s", domain, exc)
        return None

    if w is None:
        return None

    creation_date = w.creation_date
    if creation_date is None:
        return None

    # python-whois sometimes returns a list when multiple dates are present
    if isinstance(creation_date, list):
        creation_date = creation_date[0]

    if not isinstance(creation_date, datetime):
        return None

    # Make timezone-aware so subtraction with utcnow() works cleanly
    if creation_date.tzinfo is None:
        creation_date = creation_date.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    if creation_date > now:
        return None  # bogus date

    delta_days = (now - creation_date).days
    return round(delta_days / 365.25, 1)


def get_domain_age(domain: str) -> Optional[float]:
    """
    Return domain age in years (float) or None.

    - Strips scheme / path from *domain* automatically.
    - Results are cached via diskcache.
    - Hard 10-second timeout: if WHOIS hangs, returns None (never crashes).
    """
    domain = _strip_scheme(domain)
    if not domain:
        return None

    store = get_store()
    cache_key = store.make_key("whois_v2", domain)

    cached = store.get(cache_key)
    if cached is not None:
        log.info("whois cache HIT  %s → %.1f yr", domain, cached if cached else 0)
        return cached

    log.info("whois cache MISS — querying for %s", domain)

    result: Optional[float] = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_lookup_whois_blocking, domain)
        try:
            result = future.result(timeout=WHOIS_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            log.warning("WHOIS timeout (>%ds) for %s — returning None", WHOIS_TIMEOUT_S, domain)
            future.cancel()
        except Exception as exc:
            log.warning("WHOIS unexpected error for %s: %s", domain, exc)

    # Cache even None so we don't hammer WHOIS servers on repeated misses
    store.set(cache_key, result)
    log.info("whois %s → %s yr", domain, result)
    return result


# ---------------------------------------------------------------------------
# CrewAI Tool wrapper
# ---------------------------------------------------------------------------

class WhoisInput(BaseModel):
    domain: str = Field(
        description="Domain to look up, e.g. 'example.com' or 'https://example.com/page'"
    )


class WhoisTool(BaseTool):
    name: str = "domain_age_lookup"
    description: str = (
        "Look up the registration age of a domain in years via WHOIS. "
        "Older domains (>5 years) indicate an established business. Returns null on failure."
    )
    args_schema: Type[BaseModel] = WhoisInput

    def _run(self, domain: str) -> str:
        age = get_domain_age(domain)
        return json.dumps({"domain": _strip_scheme(domain), "age_years": age}, indent=2)
