"""Real website health-check tool — checks SSL, response time, mobile meta tag."""
from __future__ import annotations

import logging
import time
from typing import Optional, Type

import requests
from bs4 import BeautifulSoup
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from karyo.cache.store import get_store
from karyo.models.schemas import WebsiteHealth

log = logging.getLogger(__name__)

TIMEOUT_S = 8          # HTTP request timeout in seconds
SLOW_THRESHOLD_MS = 3000  # anything above this is "slow"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; KaryoAgent/0.1; +https://karyo.in/bot)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.5",
}


def _normalise_url(url: str) -> str:
    """Ensure URL has a scheme."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return "http://" + url
    return url


def check_website(url: str) -> WebsiteHealth:
    """
    Perform a real HTTP health check on *url*.

    Checks:
    - Reachability and HTTP status
    - Response time (ms)
    - SSL (whether final URL is HTTPS after redirects)
    - Last-Modified header
    - <meta name="viewport"> presence (mobile-friendliness proxy)

    Returns a WebsiteHealth model. Never raises.
    Results are cached.
    """
    url = _normalise_url(url)
    store = get_store()
    cache_key = store.make_key("website_v2", url)

    cached = store.get(cache_key)
    if cached is not None:
        log.info("website cache HIT  %s", url)
        return WebsiteHealth(**cached)

    log.info("website cache MISS — checking %s", url)
    health = _do_check(url)
    store.set(cache_key, health.model_dump())
    return health


def _do_check(url: str) -> WebsiteHealth:
    start = time.monotonic()

    # ------------------------------------------------------------------ #
    # Attempt 1: fetch as-is (follows redirects by default)
    # ------------------------------------------------------------------ #
    try:
        resp = requests.get(
            url,
            timeout=TIMEOUT_S,
            headers=_HEADERS,
            allow_redirects=True,
            verify=True,     # enforce SSL cert validation first pass
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return _build_health(resp, elapsed_ms)

    except requests.exceptions.SSLError:
        # Site exists but has an SSL problem — retry without verify to get HTML
        elapsed_ms = int((time.monotonic() - start) * 1000)
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(
                url,
                timeout=TIMEOUT_S,
                headers=_HEADERS,
                allow_redirects=True,
                verify=False,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            health = _build_health(resp, elapsed_ms)
            # Override SSL flag — cert was invalid
            return health.model_copy(update={"has_ssl": False})
        except Exception:
            return WebsiteHealth(
                status="dead",
                response_time_ms=elapsed_ms,
                has_ssl=False,
            )

    except requests.exceptions.Timeout:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info("Timeout checking %s (%d ms)", url, elapsed_ms)
        return WebsiteHealth(
            status="slow",
            response_time_ms=elapsed_ms,
            has_ssl=url.startswith("https://"),
        )

    except requests.exceptions.ConnectionError as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.info("Connection error checking %s: %s", url, exc)
        return WebsiteHealth(
            status="dead",
            response_time_ms=elapsed_ms,
            has_ssl=False,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log.warning("Unexpected error checking %s: %s", url, exc)
        return WebsiteHealth(
            status="dead",
            response_time_ms=elapsed_ms,
            has_ssl=False,
        )


def _build_health(resp: requests.Response, elapsed_ms: int) -> WebsiteHealth:
    """Build WebsiteHealth from a successful requests.Response."""
    final_url: str = resp.url
    has_ssl = final_url.startswith("https://")

    # HTTP status → status field
    if resp.status_code >= 500:
        status = "dead"
    elif resp.status_code >= 400:
        status = "dead"
    elif elapsed_ms > SLOW_THRESHOLD_MS:
        status = "slow"
    else:
        status = "alive"

    # Last-Modified header (raw string value)
    last_modified: Optional[str] = resp.headers.get("Last-Modified")

    # Mobile meta: look for <meta name="viewport">
    mobile_meta: Optional[bool] = None
    content_type = resp.headers.get("Content-Type", "")
    if "html" in content_type.lower() and len(resp.content) < 5_000_000:
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            mobile_meta = bool(
                soup.find("meta", attrs={"name": lambda v: v and v.lower() == "viewport"})
            )
        except Exception:
            mobile_meta = None

    return WebsiteHealth(
        status=status,
        response_time_ms=elapsed_ms,
        has_ssl=has_ssl,
        last_modified=last_modified,
        mobile_meta_tag=mobile_meta,
    )


# ---------------------------------------------------------------------------
# CrewAI Tool wrapper
# ---------------------------------------------------------------------------

class WebsiteInput(BaseModel):
    url: str = Field(description="Full URL of the website to check (e.g. https://example.com)")


class WebsiteCheckTool(BaseTool):
    name: str = "website_health_check"
    description: str = (
        "Check the health of a business website: response time (ms), SSL certificate, "
        "HTTP status, Last-Modified header, and mobile viewport meta tag presence."
    )
    args_schema: Type[BaseModel] = WebsiteInput

    def _run(self, url: str) -> str:
        import json
        health = check_website(url)
        return json.dumps(health.model_dump(), indent=2)
