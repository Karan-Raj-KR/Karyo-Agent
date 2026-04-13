"""Researcher agent — builds BusinessDossier for each lead candidate."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from crewai import Agent

from karyo.models.schemas import BusinessDossier
from karyo.tools.places import PlacesTool
from karyo.tools.website import WebsiteCheckTool
from karyo.tools.whois_tool import WhoisTool

if TYPE_CHECKING:
    from crewai import LLM

_PROMPT = (Path(__file__).parents[2] / "prompts" / "researcher.md").read_text()


def get_researcher_agent(llm: "LLM") -> Agent:
    return Agent(
        role="Lead Researcher",
        goal=(
            "Research local businesses to build rich dossiers on their digital presence, "
            "website health, and review standing."
        ),
        backstory=_PROMPT,
        tools=[PlacesTool(), WebsiteCheckTool(), WhoisTool()],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )


# ---------------------------------------------------------------------------
# Stub — used when no LLM is available
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
