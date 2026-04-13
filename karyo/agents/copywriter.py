"""Copywriter agent — drafts personalised outreach emails for approved leads."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from crewai import Agent

from karyo.models.schemas import FinalLead

if TYPE_CHECKING:
    from crewai import LLM

_PROMPT = (Path(__file__).parents[2] / "prompts" / "copywriter.md").read_text()


def get_copywriter_agent(llm: "LLM") -> Agent:
    return Agent(
        role="Outreach Copywriter",
        goal=(
            "Write concise, personalised cold-outreach emails that highlight "
            "specific digital gaps and position our agency as the clear solution."
        ),
        backstory=_PROMPT,
        tools=[],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )


# ---------------------------------------------------------------------------
# Stub — returns a templated email (real LLM copy comes later)
# ---------------------------------------------------------------------------

def stub_copy(lead: FinalLead) -> str:
    d = lead.dossier
    s = lead.score
    issues = s.primary_gap or "your digital presence"

    lines = [
        f"Subject: Quick question about {d.name}'s online presence",
        "",
        f"Hi {d.name} Team,",
        "",
        f"I came across {d.name} on Google — {d.review_count} reviews and a "
        f"{d.google_rating or 'solid'}-star rating speaks for itself. Impressive.",
        "",
        f"One thing caught my attention though: {issues}. "
        "In a competitive local market, those gaps quietly push potential patients "
        "toward clinics that show up better online.",
        "",
        "We help dental clinics in Bengaluru fix exactly this — "
        "usually within 30 days, no long-term contract needed.",
        "",
        "Worth a 15-minute call this week?",
        "",
        "Best,",
        "Karan | KĀRYO Digital",
        "karan@karyo.in | +91 98765 43210",
        "",
        "---",
        f"[STUB EMAIL — lead score {s.combined_score}/20 | flag: {s.flag}]",
    ]
    return "\n".join(lines)
