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

_SYSTEM_PROMPT = (Path(__file__).parents[2] / "prompts" / "copywriter.md").read_text()
_GROQ_MODEL    = "llama-3.3-70b-versatile"
_TEMPERATURE   = 0.75   # enough variation; not so high it ignores rules

_WORD_MIN, _WORD_MAX = 100, 140


# ── helpers ────────────────────────────────────────────────────────────────────

def _body_word_count(email: str) -> int:
    """Count words in the body only (between 'Hi ' and 'Best,')."""
    m = re.search(r"Hi .+?\n(.+?)(?=\nBest,|\nRegards,|\Z)", email, re.DOTALL)
    text = m.group(1) if m else email
    return len(text.split())


def _clean(text: str) -> str:
    """Strip markdown code fences if the LLM wrapped its output."""
    text = text.strip()
    text = re.sub(r"^```[a-z]*\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _lead_context(lead: FinalLead) -> str:
    """Format the dossier as labelled key-value pairs for the LLM."""
    d = lead.dossier
    s = lead.score
    lines = [
        f"Business name    : {d.name}",
        f"Category         : dental clinic",
        f"Address          : {d.address}",
        f"Phone            : {d.phone or 'NOT LISTED — no phone anywhere online'}",
        f"Website          : {d.website or 'NONE'}",
        f"Website status   : {d.website_status}",
        f"Has SSL          : {d.has_ssl}",
        f"Domain age       : {f'{d.domain_age_years} years' if d.domain_age_years else 'N/A'}",
        f"Google rating    : {d.google_rating or 'unknown'}",
        f"Review count     : {d.review_count}",
        f"Primary gap      : {s.primary_gap}",
        f"Research notes   :",
    ]
    for note in d.research_notes:
        lines.append(f"  - {note}")
    return "\n".join(lines)


def _call_groq(client, messages: list[dict]) -> str:
    resp = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=messages,
        temperature=_TEMPERATURE,
        max_tokens=450,
    )
    return _clean(resp.choices[0].message.content or "")


# ── main public function ───────────────────────────────────────────────────────

def real_copy(lead: FinalLead) -> str:
    """
    Generate a 100-140 word personalised cold-outreach email via Groq.

    - Cache key: (business_name, primary_gap) — stable across re-research runs
    - Validates word count; retries once with explicit correction instruction
    - Falls back to stub_copy() if no API key
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        log.warning("[copywriter] No GROQ_API_KEY — using stub fallback")
        return stub_copy(lead)

    store     = get_store()
    cache_key = store.make_key(
        "copywriter_v3", lead.dossier.name, lead.score.primary_gap
    )
    cached = store.get(cache_key)
    if cached is not None:
        log.info("[copywriter] cache HIT  %s", lead.dossier.name)
        return cached

    from groq import Groq
    client = Groq(api_key=groq_key)

    context = _lead_context(lead)
    user_msg = (
        "Write a cold outreach email for the following lead. "
        "Follow EVERY rule in your instructions — especially word count and the hard rules.\n\n"
        f"{context}"
    )
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]

    # ── attempt 1 ─────────────────────────────────────────────────────────────
    try:
        email = _call_groq(client, messages)
    except Exception as exc:
        log.warning("[copywriter] Groq error for %s: %s", lead.dossier.name, exc)
        return stub_copy(lead)

    wc = _body_word_count(email)
    log.info("[copywriter] %s — attempt 1: %d words", lead.dossier.name, wc)

    # ── retry if word count outside 100-140 ───────────────────────────────────
    if not (_WORD_MIN <= wc <= _WORD_MAX):
        direction = "shorter" if wc > _WORD_MAX else "longer"
        retry_messages = messages + [
            {"role": "assistant", "content": email},
            {
                "role": "user",
                "content": (
                    f"The body is {wc} words. It must be exactly {_WORD_MIN}–{_WORD_MAX} words. "
                    f"Rewrite it to be {direction}, keeping every hard rule. "
                    f"Return only the full email — no explanation."
                ),
            },
        ]
        try:
            email = _call_groq(client, retry_messages)
            wc = _body_word_count(email)
            log.info("[copywriter] %s — retry: %d words", lead.dossier.name, wc)
        except Exception as exc:
            log.warning("[copywriter] retry error for %s: %s", lead.dossier.name, exc)

    store.set(cache_key, email)
    return email


# ── CrewAI agent wrapper ───────────────────────────────────────────────────────

def get_copywriter_agent(llm: "LLM") -> Agent:
    return Agent(
        role="Outreach Copywriter",
        goal=(
            "Write 100-140 word personalised cold-outreach emails in KĀRYO's voice "
            "that reference specific digital gaps and end with a low-commitment ask."
        ),
        backstory=_SYSTEM_PROMPT,
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
    gap  = s.primary_gap or "no digital presence"

    if d.website_status == "none":
        line1 = f"{d.name} has no website — invisible to every patient searching online."
    elif d.website_status == "dead":
        line1 = f"The website at {d.website} is unreachable — patients clicking it bounce immediately."
    else:
        line1 = f"{d.name} loads slowly — most mobile users won't wait."

    extra = (
        "Zero reviews means patients have no social proof to trust the practice."
        if d.review_count == 0
        else f"With only {d.review_count} reviews, online credibility is still low."
    )

    return (
        f"Subject: {d.name} — are new patients finding you?\n"
        "\n"
        f"Hi {d.name},\n"
        "\n"
        f"{line1} The core gap: {gap}.\n"
        f"{extra} In Indiranagar's competitive dental market, "
        "that means patients go elsewhere.\n"
        "\n"
        "KĀRYO Digital helps dental clinics in Bangalore build a presence that "
        "converts — website, local SEO, and trust signals, usually live in 3 weeks.\n"
        "\n"
        "Would a 15-min call this week work?\n"
        "\n"
        "Best,\n"
        "Karan & Havinash\n"
        "KĀRYO Digital, Bangalore"
    )
