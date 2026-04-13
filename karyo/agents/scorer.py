"""Scorer agent — converts BusinessDossier into a LeadScore."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from crewai import Agent

from karyo.models.schemas import BusinessDossier, LeadScore

if TYPE_CHECKING:
    from crewai import LLM

_PROMPT = (Path(__file__).parents[2] / "prompts" / "scorer.md").read_text()


def get_scorer_agent(llm: "LLM") -> Agent:
    return Agent(
        role="Lead Scorer",
        goal=(
            "Evaluate each business dossier and assign presence gap and "
            "conversion likelihood scores between 1-10."
        ),
        backstory=_PROMPT,
        tools=[],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )


# ---------------------------------------------------------------------------
# Stub — deterministic scoring rules for demo purposes
# ---------------------------------------------------------------------------

def stub_score(dossier: BusinessDossier) -> LeadScore:
    """Return a hardcoded LeadScore derived from obvious dossier signals."""
    # Presence gap: higher = bigger gap = better lead
    gap = 5
    if dossier.website_status in ("none", "dead"):
        gap += 3
    elif dossier.website_status == "slow":
        gap += 2
    if dossier.has_ssl is False:
        gap += 1
    if dossier.instagram_handle is None:
        gap += 1
    gap = min(gap, 10)

    # Conversion likelihood: driven by review count and rating
    conv = 5
    if dossier.review_count < 50:
        conv += 2   # small businesses easier to convert
    if dossier.google_rating and dossier.google_rating >= 4.0:
        conv += 1   # decent rep, cares about image
    if dossier.domain_age_years and dossier.domain_age_years < 5:
        conv += 1   # younger domain — still growing
    conv = min(conv, 10)

    combined = gap + conv
    flag = "approve" if combined >= 14 else ("reject" if combined <= 9 else "borderline")

    primary_gaps = []
    if dossier.website_status in ("none", "dead"):
        primary_gaps.append("No website")
    elif dossier.website_status == "slow":
        primary_gaps.append("Slow website")
    if dossier.has_ssl is False:
        primary_gaps.append("No SSL")
    if dossier.instagram_handle is None:
        primary_gaps.append("No Instagram")
    primary_gap = " + ".join(primary_gaps) if primary_gaps else "Minor gaps only"

    return LeadScore(
        business_name=dossier.name,
        presence_gap_score=gap,
        conversion_likelihood=conv,
        combined_score=combined,
        reasoning=(
            f"{dossier.name} has a gap score of {gap}/10 and conversion likelihood "
            f"of {conv}/10. Key issues: {primary_gap}."
        ),
        primary_gap=primary_gap,
        flag=flag,
    )
