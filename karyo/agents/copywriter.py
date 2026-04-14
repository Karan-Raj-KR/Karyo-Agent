"""Copywriter agent — real Groq LLM email per approved lead, fully cached."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from crewai import Agent

from karyo.cache.store import get_store
from karyo.models.schemas import FinalLead

if TYPE_CHECKING:
    from crewai import LLM

log = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parents[2] / "prompts" / "copywriter.md").read_text()

_GROQ_MODEL  = "llama-3.3-70b-versatile"
_TEMPERATURE = 0.7   # higher than scorer — we want creative variation


# ── dossier context builder ────────────────────────────────────────────────────

def _lead_context(lead: FinalLead) -> str:
    """Return a structured text block the LLM uses to personalise the email."""
    d = lead.dossier
    s = lead.score

    lines = [
        f"Business name   : {d.name}",
        f"Address         : {d.address}",
        f"Phone           : {d.phone or 'NOT LISTED — no phone anywhere online'}",
        f"Website         : {d.website or 'NONE — business has no website'}",
        f"Website status  : {d.website_status}",
        f"Has SSL         : {d.has_ssl}",
        f"Domain age      : {f'{d.domain_age_years} years' if d.domain_age_years else 'N/A'}",
        f"Google rating   : {d.google_rating or 'unknown'}",
        f"Review count    : {d.review_count}",
        f"Primary gap     : {s.primary_gap}",
        f"Presence gap    : {s.presence_gap_score}/10",
        f"Conv likelihood : {s.conversion_likelihood}/10",
        f"Research notes  :",
    ]
    for note in d.research_notes:
        lines.append(f"  - {note}")
    return "\n".join(lines)


# ── strip markdown if LLM wraps in code fences ────────────────────────────────

def _clean(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── real Groq email writer ─────────────────────────────────────────────────────

def real_copy(lead: FinalLead) -> str:
    """
    Generate a personalised cold-outreach email via Groq.

    Falls back to stub_copy() if no API key.
    Result is cached by (business_name, dossier_hash) — re-generated if dossier changes.
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        log.warning("[copywriter] No GROQ_API_KEY — using stub fallback")
        return stub_copy(lead)

    store    = get_store()
    cache_key = store.make_key(
        "copywriter_v2", lead.dossier.name, lead.dossier.model_dump_json()
    )
    cached = store.get(cache_key)
    if cached is not None:
        log.info("[copywriter] cache HIT  %s", lead.dossier.name)
        return cached

    from groq import Groq
    client = Groq(api_key=groq_key)

    user_msg = (
        "Write a cold outreach email for this lead. Follow every rule in your "
        "instructions — especially the ABSOLUTE BANS. Use the dossier data below "
        "to make the email specific to THIS business. Do not copy phrases from "
        "other emails you may have written.\n\n"
        f"{_lead_context(lead)}"
    )

    try:
        resp = client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[
                {"role": "system", "content": _PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            temperature=_TEMPERATURE,
            max_tokens=400,
        )
        email = _clean(resp.choices[0].message.content or "")
    except Exception as exc:
        log.warning("[copywriter] Groq error for %s: %s", lead.dossier.name, exc)
        return stub_copy(lead)

    store.set(cache_key, email)
    return email


# ── CrewAI agent wrapper ───────────────────────────────────────────────────────

def get_copywriter_agent(llm: "LLM") -> Agent:
    return Agent(
        role="Outreach Copywriter",
        goal=(
            "Write concise, personalised cold-outreach emails that highlight "
            "specific digital gaps and position KĀRYO as the clear solution."
        ),
        backstory=_PROMPT,
        tools=[],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )


# ── Stub fallback ──────────────────────────────────────────────────────────────

def stub_copy(lead: FinalLead) -> str:
    """Deterministic template — used only when no API key is set."""
    d = lead.dossier
    s = lead.score
    gap = s.primary_gap or "no digital presence"

    opener = (
        f"{d.name} has no website in 2026 — invisible to every patient searching online."
        if d.website_status == "none"
        else f"The website at {d.website} is currently unreachable — patients clicking it leave immediately."
        if d.website_status == "dead"
        else f"{d.name} loads in over 3 seconds — most mobile users won't wait."
    )

    return (
        f"Subject: {d.name} — quick question\n"
        "\n"
        f"Hi {d.name} Team,\n"
        "\n"
        f"{opener}\n"
        "\n"
        f"The core issue: {gap}. "
        "In Indiranagar's competitive dental market that means patients go elsewhere.\n"
        "\n"
        "We fix this for local clinics — usually live within 3 weeks.\n"
        "\n"
        "Worth a 5-minute call this week?\n"
        "\n"
        "Best,\n"
        "Karan | KĀRYO Digital\n"
        "karan@karyo.in | +91 98765 43210"
    )
