"""
Scorer agent — calls Groq LLM directly to score each BusinessDossier.

Execution modes
---------------
LIVE  : GROQ_API_KEY is set → real llama-3.3-70b-versatile call per business
STUB  : no key            → deterministic rule-based fallback (stub_score)
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from crewai import Agent
from rich.console import Console

from karyo.cache.store import get_store
from karyo.models.schemas import BusinessDossier, LeadScore

if TYPE_CHECKING:
    from crewai import LLM

log = logging.getLogger(__name__)
console = Console()

_RUBRIC_PROMPT = (Path(__file__).parents[2] / "prompts" / "scorer.md").read_text()

# ── flag thresholds ────────────────────────────────────────────────────────────
_FLAG_APPROVE  = 16
_FLAG_REJECT   = 8

_GROQ_MODEL    = "llama-3.3-70b-versatile"
_MAX_TOKENS    = 512
_TEMPERATURE   = 0.2

_SYSTEM_PROMPT = f"""You are a lead-scoring specialist for a digital marketing agency.
Your job is to evaluate local businesses and decide how valuable they are as sales leads.

{_RUBRIC_PROMPT}

IMPORTANT RULES:
- Respond with ONLY a raw JSON object — no markdown, no code fences, no prose.
- All scores must be integers between 1 and 10.
- "reasoning" must be 2–3 sentences explaining the scores.
- "primary_gap" is the single biggest addressable issue (e.g. "No website", "Dead website + No SSL").

Required JSON shape (nothing else):
{{
  "presence_gap_score": <int 1-10>,
  "conversion_likelihood": <int 1-10>,
  "reasoning": "<2-3 sentences>",
  "primary_gap": "<single biggest gap>"
}}"""


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    """Strip markdown fences and parse the first JSON object in *text*."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ``` wrappers
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting the first {...} block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def _dossier_to_prompt(dossier: BusinessDossier) -> str:
    """Format the dossier fields the LLM should reason over."""
    return json.dumps(
        {
            "name":              dossier.name,
            "website_status":    dossier.website_status,
            "has_ssl":           dossier.has_ssl,
            "domain_age_years":  dossier.domain_age_years,
            "google_rating":     dossier.google_rating,
            "review_count":      dossier.review_count,
            "phone":             dossier.phone,
            "research_notes":    dossier.research_notes,
        },
        ensure_ascii=False,
        indent=2,
    )


def _flag(combined: int) -> str:
    if combined >= _FLAG_APPROVE:
        return "approve"
    if combined <= _FLAG_REJECT:
        return "reject"
    return "borderline"


# ── Groq call with retry ───────────────────────────────────────────────────────

def _score_one_groq(client, dossier: BusinessDossier) -> Optional[dict]:
    """
    Call Groq once (retry on bad JSON). Returns raw LLM dict or None.
    """
    user_msg = (
        f"Score this business as a digital-marketing lead:\n\n{_dossier_to_prompt(dossier)}"
    )

    # ── attempt 1 ─────────────────────────────────────────────────────────────
    resp1 = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=_TEMPERATURE,
        max_tokens=_MAX_TOKENS,
    )
    raw1 = resp1.choices[0].message.content or ""
    parsed = _extract_json(raw1)
    if parsed is not None:
        return parsed

    # ── attempt 2: two-turn correction ────────────────────────────────────────
    log.warning("[scorer] JSON parse failed for '%s' — retrying", dossier.name)
    resp2 = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {"role": "system",    "content": _SYSTEM_PROMPT},
            {"role": "user",      "content": user_msg},
            {"role": "assistant", "content": raw1},
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Return ONLY the JSON object — no markdown, no explanation, no code fences."
                ),
            },
        ],
        temperature=0.0,
        max_tokens=_MAX_TOKENS,
    )
    raw2 = resp2.choices[0].message.content or ""
    parsed2 = _extract_json(raw2)
    if parsed2 is None:
        log.warning("[scorer] Retry also failed for '%s' — skipping", dossier.name)
    return parsed2


# ── public: real LLM scorer ───────────────────────────────────────────────────

def real_score_all(
    dossiers: list[BusinessDossier],
    *,
    limit: int = 20,
) -> list[LeadScore]:
    """
    Score every dossier using Groq llama-3.3-70b-versatile.

    Falls back to stub_score() if GROQ_API_KEY is not set.
    Results are cached per (business_name, dossier_hash).
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        log.warning("[scorer] No GROQ_API_KEY — falling back to stub scoring")
        return [stub_score(d) for d in dossiers[:limit]]

    from groq import Groq  # imported lazily so stub mode has no groq dep
    client = Groq(api_key=groq_key)
    store  = get_store()

    scores: list[LeadScore] = []
    batch  = dossiers[:limit]

    for idx, dossier in enumerate(batch, 1):
        # ── cache key: name + full dossier hash ───────────────────────────────
        dossier_hash = store.make_key("llm_score_v1", dossier.name, dossier.model_dump_json())
        cached = store.get(dossier_hash)

        if cached is not None:
            score = LeadScore(**cached)
            flag_sym = {"approve": "[green]✓[/]", "reject": "[red]✗[/]", "borderline": "[yellow]~[/]"}
            console.print(
                f"  [dim]{idx:>2}/{len(batch)}[/] {dossier.name[:40]:<40} "
                f"{flag_sym.get(score.flag, '?')} [dim]cached[/]"
            )
            scores.append(score)
            continue

        # ── live Groq call ─────────────────────────────────────────────────────
        console.print(
            f"  [dim]{idx:>2}/{len(batch)}[/] {dossier.name[:40]:<40} "
            f"[dim]scoring…[/]",
            end="",
        )
        try:
            raw = _score_one_groq(client, dossier)
        except Exception as exc:
            log.warning("[scorer] Groq call error for '%s': %s", dossier.name, exc)
            console.print(f" [red]ERROR[/] ({exc})")
            continue

        if raw is None:
            console.print(" [red]SKIP[/] (unparseable JSON after retry)")
            continue

        # ── validate & clamp ──────────────────────────────────────────────────
        try:
            gap  = max(1, min(10, int(raw["presence_gap_score"])))
            conv = max(1, min(10, int(raw["conversion_likelihood"])))
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("[scorer] Bad numeric fields for '%s': %s", dossier.name, exc)
            console.print(f" [red]SKIP[/] (bad numeric fields)")
            continue

        combined = gap + conv
        flag     = _flag(combined)

        score = LeadScore(
            business_name       = dossier.name,
            presence_gap_score  = gap,
            conversion_likelihood = conv,
            combined_score      = combined,
            reasoning           = str(raw.get("reasoning", "")),
            primary_gap         = str(raw.get("primary_gap", "Unknown")),
            flag                = flag,
        )

        store.set(dossier_hash, score.model_dump())

        flag_sym = {"approve": "[green]✓ APPROVE[/]", "reject": "[red]✗ REJECT[/]", "borderline": "[yellow]~ BORDER[/]"}
        console.print(
            f" gap={gap} conv={conv} combined={combined} "
            f"{flag_sym.get(flag, flag)}"
        )
        scores.append(score)

    return scores


# ── CrewAI Agent wrapper (for live crew pipeline) ─────────────────────────────

def get_scorer_agent(llm: "LLM") -> Agent:
    return Agent(
        role="Lead Scorer",
        goal=(
            "Evaluate each business dossier and assign presence gap and "
            "conversion likelihood scores between 1-10."
        ),
        backstory=_RUBRIC_PROMPT,
        tools=[],
        llm=llm,
        allow_delegation=False,
        verbose=True,
    )


# ── Stub fallback ─────────────────────────────────────────────────────────────

def stub_score(dossier: BusinessDossier) -> LeadScore:
    """Deterministic rule-based scorer — used when no API key is available."""
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

    conv = 5
    if dossier.review_count < 50:
        conv += 2
    if dossier.google_rating and dossier.google_rating >= 4.0:
        conv += 1
    if dossier.domain_age_years and dossier.domain_age_years < 5:
        conv += 1
    conv = min(conv, 10)

    combined = gap + conv
    flag = _flag(combined)

    primary_gaps = []
    if dossier.website_status in ("none", "dead"):
        primary_gaps.append("No website" if dossier.website_status == "none" else "Dead website")
    elif dossier.website_status == "slow":
        primary_gaps.append("Slow website")
    if dossier.has_ssl is False:
        primary_gaps.append("No SSL")
    if dossier.instagram_handle is None:
        primary_gaps.append("No Instagram")
    primary_gap = " + ".join(primary_gaps) if primary_gaps else "Minor gaps only"

    return LeadScore(
        business_name         = dossier.name,
        presence_gap_score    = gap,
        conversion_likelihood = conv,
        combined_score        = combined,
        reasoning             = (
            f"{dossier.name} has a gap score of {gap}/10 and conversion likelihood "
            f"of {conv}/10. Key issues: {primary_gap}."
        ),
        primary_gap           = primary_gap,
        flag                  = flag,
    )
