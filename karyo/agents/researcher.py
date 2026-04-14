"""Researcher agent — builds BusinessDossier for each lead candidate."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from crewai import Agent
from crewai.tools import tool

from karyo.models.schemas import BusinessDossier
from karyo.tools.places import PlacesTool, fetch_places
from karyo.tools.website import WebsiteCheckTool, check_website
from karyo.tools.whois_tool import WhoisTool, get_domain_age

if TYPE_CHECKING:
    from crewai import LLM

log = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parents[2] / "prompts" / "researcher.md").read_text()


# ---------------------------------------------------------------------------
# @tool-decorated wrappers — visible to the LLM inside CrewAI tasks
# ---------------------------------------------------------------------------

@tool("fetch_places")
def fetch_places_tool(city: str, category: str) -> str:
    """Search OpenStreetMap for local businesses matching category in city.
    Returns a JSON list of businesses with name, address, phone, website."""
    results = fetch_places(city=city, category=category)
    return json.dumps(results[:20], ensure_ascii=False, indent=2)


@tool("website_health_check")
def website_health_check_tool(url: str) -> str:
    """Check a business website: status (alive/dead/slow), SSL, response time.
    Pass the full URL including http/https scheme."""
    if not url:
        return json.dumps({"status": "none"})
    try:
        health = check_website(url)
        return json.dumps(health.model_dump(), ensure_ascii=False)
    except Exception as exc:
        log.warning("website_health_check failed for %s: %s", url, exc)
        return json.dumps({"status": "dead"})


@tool("domain_age")
def domain_age_tool(domain: str) -> str:
    """Return the age of a domain in years via WHOIS. Accepts full URLs or bare domains."""
    if not domain:
        return json.dumps({"age_years": None})
    try:
        age = get_domain_age(domain)
        return json.dumps({"age_years": age})
    except Exception as exc:
        log.warning("domain_age failed for %s: %s", domain, exc)
        return json.dumps({"age_years": None})


# ---------------------------------------------------------------------------
# CrewAI Agent definition
# ---------------------------------------------------------------------------

def get_researcher_agent(llm: "LLM") -> Agent:
    return Agent(
        role="Lead Researcher",
        goal=(
            "Research local businesses to build rich dossiers on their digital presence, "
            "website health, and review standing."
        ),
        backstory=_PROMPT,
        tools=[
            PlacesTool(),
            WebsiteCheckTool(),
            WhoisTool(),
            fetch_places_tool,
            website_health_check_tool,
            domain_age_tool,
        ],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )


# ---------------------------------------------------------------------------
# Real pipeline — no LLM required, uses actual tool functions directly
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """Strip scheme/path from a URL to get a bare domain string."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return url


def real_research(city: str, category: str, limit: int = 20) -> list[BusinessDossier]:
    """
    Run the full research pipeline using real tool calls.

    1. fetch_places(city, category)        → up to *limit* raw business dicts
    2. check_website(url)                  → WebsiteHealth (if website present)
    3. get_domain_age(domain)              → float years (if website present)
    4. Return list[BusinessDossier]

    Never raises — all failures are caught and result in None/default fields.
    """
    log.info("real_research: fetching places for %s / %s", city, category)
    businesses = fetch_places(city=city, category=category)
    businesses = businesses[:limit]
    log.info("real_research: got %d businesses", len(businesses))

    dossiers: list[BusinessDossier] = []

    for idx, biz in enumerate(businesses):
        name = biz.get("name", f"Business #{idx}")
        place_id = biz.get("place_id", f"unknown:{idx}")
        address = biz.get("address") or city
        phone = biz.get("phone")  # may be None
        website = biz.get("website")  # may be None

        # --- Website health check ---
        website_status = "none"
        has_ssl: bool | None = None
        response_time_ms: int | None = None
        mobile_meta: bool | None = None
        notes: list[str] = []

        if website:
            try:
                health = check_website(website)
                website_status = health.status
                has_ssl = health.has_ssl
                response_time_ms = health.response_time_ms
                mobile_meta = health.mobile_meta_tag

                if not has_ssl:
                    notes.append("No SSL certificate — browser shows 'Not Secure'")
                if health.status == "slow":
                    notes.append(f"Slow website ({response_time_ms} ms) — poor UX")
                elif health.status == "dead":
                    notes.append("Website unreachable or returns error")
                if mobile_meta is False:
                    notes.append("Missing mobile viewport meta tag — not mobile-friendly")
            except Exception as exc:
                log.warning("check_website raised for %s (%s): %s", name, website, exc)
                website_status = "dead"
                notes.append(f"Website check failed: {exc}")
        else:
            notes.append("No website listed on OpenStreetMap")

        # --- Domain age ---
        domain_age_years: float | None = None
        if website:
            try:
                domain = _extract_domain(website)
                domain_age_years = get_domain_age(domain)
                if domain_age_years is not None:
                    notes.append(f"Domain age: {domain_age_years:.1f} years")
            except Exception as exc:
                log.warning("get_domain_age raised for %s (%s): %s", name, website, exc)

        # --- Phone note ---
        if not phone:
            notes.append("Phone number not listed")

        dossier = BusinessDossier(
            name=name,
            place_id=place_id,
            address=address,
            phone=phone,
            website=website,
            website_status=website_status,
            has_ssl=has_ssl,
            domain_age_years=domain_age_years,
            google_rating=biz.get("google_rating"),
            review_count=biz.get("review_count", 0),
            instagram_handle=None,
            instagram_last_post_days=None,
            research_notes=notes,
        )
        dossiers.append(dossier)
        log.info(
            "[%d/%d] %s → status=%s ssl=%s age=%s",
            idx + 1, len(businesses), name,
            website_status, has_ssl, domain_age_years,
        )

    return dossiers


# ---------------------------------------------------------------------------
# Stub — kept for backward compatibility (Scorer/Manager/Copywriter stubs use it)
# ---------------------------------------------------------------------------

def stub_research(business: dict, location: str) -> BusinessDossier:
    """Return a hardcoded BusinessDossier for a stub business dict."""
    website = business.get("website")
    return BusinessDossier(
        name=business["name"],
        place_id=business["place_id"],
        address=business["address"],
        phone=business.get("phone"),
        website=website,
        website_status="slow" if website and "smile" in website else ("alive" if website else "none"),
        has_ssl=False if website and "http://" in website else (True if website else None),
        domain_age_years=3.2 if website and "smile" in website else (8.7 if website else None),
        google_rating=business.get("google_rating"),
        review_count=business.get("review_count", 0),
        instagram_handle=None,
        instagram_last_post_days=None,
        research_notes=[
            "No SSL certificate detected" if website and "http://" in website else "SSL present",
            "Website loads in >3s — poor UX" if website and "smile" in website else "Fast load time",
            "No Instagram presence found" if not business.get("instagram") else "Instagram active",
        ],
    )
