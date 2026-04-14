"""
Real Manager agent — self-correction loop with Groq LLM.

Pipeline (6 steps)
------------------
1  Receive list[LeadScore] + list[BusinessDossier]
2  First pass: auto-approve (≥16), auto-reject (≤8), tag 9-15 as borderline
3  Generate a specific follow-up query per borderline via Groq
4  Re-research each borderline (website re-check + follow-up note) then re-score
5  Collect all approved leads, return top 5 by combined_score as list[FinalLead]
6  Every decision is logged to run_log entries and printed to the rich terminal
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from crewai import Agent
from rich.console import Console

from karyo.cache.store import get_store
from karyo.models.schemas import (
    BusinessDossier,
    FinalLead,
    LeadScore,
    ManagerDecision,
)
from karyo.ui.console import print_manager_decision, print_manager_phase

if TYPE_CHECKING:
    from crewai import LLM

log = logging.getLogger(__name__)
console = Console()

_GROQ_MODEL  = "llama-3.3-70b-versatile"
_AUTO_APPROVE_THRESHOLD      = 16   # pass 1: clear approve
_AUTO_APPROVE_THRESHOLD_P2   = 13   # pass 2: verified leads approved at lower bar
_AUTO_REJECT_THRESHOLD       = 8


# ── Groq follow-up query ───────────────────────────────────────────────────────

def _get_follow_up_query(
    client,
    store,
    dossier: BusinessDossier,
    score: LeadScore,
) -> str:
    """Ask Groq for the single most important thing to verify about this lead."""
    cache_key = store.make_key(
        "manager_followup_v1", dossier.name, score.combined_score, score.primary_gap
    )
    cached = store.get(cache_key)
    if cached:
        return cached

    if client is None:
        query = f"Is {dossier.name} actively seeking to improve their digital presence?"
        store.set(cache_key, query)
        return query

    notes_str = "; ".join(dossier.research_notes) or "none"
    prompt = (
        f"Business: {dossier.name}\n"
        f"Score: {score.combined_score}/20  (gap={score.presence_gap_score}, "
        f"conv={score.conversion_likelihood})\n"
        f"Primary gap: {score.primary_gap}\n"
        f"Research notes: {notes_str}\n\n"
        "What is the single most important thing to verify before deciding to "
        "pursue this business as a lead for a digital marketing agency? "
        "Return only one concise sentence — the research question itself, nothing else."
    )
    try:
        resp = client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise sales-intelligence analyst. "
                        "Return exactly one sentence with no preamble."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=80,
        )
        query = (resp.choices[0].message.content or "").strip().strip('"')
    except Exception as exc:
        log.warning("[manager] follow-up query error for %s: %s", dossier.name, exc)
        query = f"Does {dossier.name} have an active owner who engages with local customers online?"

    store.set(cache_key, query)
    return query


# ── Re-research a borderline dossier ──────────────────────────────────────────

def _reresearch(dossier: BusinessDossier, follow_up_query: str) -> BusinessDossier:
    """
    Enrich the dossier with a follow-up note and re-verify website health.
    Website check is cached → instant on subsequent runs.
    """
    from karyo.tools.website import check_website

    notes = list(dossier.research_notes)
    notes.append(f"Manager follow-up: {follow_up_query}")

    website_status = dossier.website_status
    has_ssl        = dossier.has_ssl

    if dossier.website:
        try:
            health = check_website(dossier.website)
            website_status = health.status
            has_ssl        = health.has_ssl
            notes.append(
                f"Re-verified website: {health.status} "
                f"({health.response_time_ms}ms, SSL={health.has_ssl})"
            )
        except Exception as exc:
            log.warning("[manager] re-check failed for %s: %s", dossier.name, exc)

    return dossier.model_copy(
        update={
            "research_notes": notes,
            "website_status": website_status,
            "has_ssl":        has_ssl,
        }
    )


# ── Re-score a single dossier ─────────────────────────────────────────────────

def _rescore(dossier: BusinessDossier) -> LeadScore:
    """Re-score using real Groq (falls back to stub if no key)."""
    from karyo.agents.scorer import real_score_all
    results = real_score_all([dossier], limit=1)
    if results:
        return results[0]
    from karyo.agents.scorer import stub_score
    return stub_score(dossier)


# ── RealManager ───────────────────────────────────────────────────────────────

class RealManager:
    """
    Plain Python class (no CrewAI task) that runs the full 6-step manager loop.
    Uses Groq API directly; falls back to deterministic logic if no key.
    """

    def __init__(self) -> None:
        self.groq_key = os.getenv("GROQ_API_KEY", "").strip()
        self.store    = get_store()
        if self.groq_key:
            from groq import Groq
            self.client: Optional[object] = Groq(api_key=self.groq_key)
        else:
            self.client = None

    def run(
        self,
        scores: list[LeadScore],
        dossiers: list[BusinessDossier],
    ) -> tuple[list[FinalLead], list[ManagerDecision], list[dict]]:
        """
        Returns
        -------
        final_leads  : top 5 approved FinalLead objects (sorted by combined_score desc)
        decisions    : every ManagerDecision (all 20 businesses)
        run_log      : list of dicts suitable for run_log.json
        """
        dossier_by_name = {d.name: d for d in dossiers}

        approvals:   list[FinalLead]      = []
        decisions:   list[ManagerDecision] = []
        run_log:     list[dict]            = []
        borderlines: list[tuple[BusinessDossier, LeadScore]] = []

        # ── STEP 2: first pass ─────────────────────────────────────────────────
        print_manager_phase("Pass 1 — first-cut decisions")

        for score in scores:
            dossier = dossier_by_name.get(score.business_name)
            if dossier is None:
                continue

            ts = datetime.now(timezone.utc).isoformat()

            if score.combined_score >= _AUTO_APPROVE_THRESHOLD:
                reason = (
                    f"AUTO-APPROVE: combined {score.combined_score}/20 ≥ {_AUTO_APPROVE_THRESHOLD}. "
                    f"{score.primary_gap}. {score.reasoning}"
                )
                dec = ManagerDecision(
                    business_name=score.business_name,
                    action="approve",
                    reason=reason,
                )
                decisions.append(dec)
                approvals.append(
                    FinalLead(
                        dossier=dossier,
                        score=score.model_copy(update={"flag": "approve"}),
                        manager_reason=reason,
                    )
                )
                print_manager_decision(dec)
                run_log.append(_log_entry(ts, dossier, score, "approve", 1, reason))

            elif score.combined_score <= _AUTO_REJECT_THRESHOLD:
                reason = (
                    f"AUTO-REJECT: combined {score.combined_score}/20 ≤ {_AUTO_REJECT_THRESHOLD}. "
                    f"Lead quality below minimum threshold."
                )
                dec = ManagerDecision(
                    business_name=score.business_name,
                    action="reject",
                    reason=reason,
                )
                decisions.append(dec)
                print_manager_decision(dec)
                run_log.append(_log_entry(ts, dossier, score, "reject", 1, reason))

            else:
                # 9-15: borderline — defer to pass 2
                borderlines.append((dossier, score))

        console.print(
            f"\n  [dim]Pass 1 complete — "
            f"{sum(1 for d in decisions if d.action == 'approve')} approved, "
            f"{sum(1 for d in decisions if d.action == 'reject')} rejected, "
            f"{len(borderlines)} borderline → going to pass 2[/]\n"
        )

        if not borderlines:
            top5 = sorted(approvals, key=lambda l: l.score.combined_score, reverse=True)[:5]
            return top5, decisions, run_log

        # ── STEP 3: follow-up queries ──────────────────────────────────────────
        print_manager_phase("Pass 2 — generating follow-up queries")

        follow_up_queries: dict[str, str] = {}
        for dossier, score in borderlines:
            query = _get_follow_up_query(self.client, self.store, dossier, score)
            follow_up_queries[dossier.name] = query
            console.print(
                f"  [cyan]{dossier.name[:42]:<42}[/] "
                f"[dim]→[/] {query}"
            )

        # ── STEP 4: re-research + re-score ────────────────────────────────────
        print_manager_phase("Pass 2 — re-research & re-score borderlines")

        for dossier, original_score in borderlines:
            follow_up = follow_up_queries[dossier.name]

            # Re-research (adds follow-up note, re-checks website from cache)
            updated = _reresearch(dossier, follow_up)

            # Re-score via Groq (new cache key because dossier changed)
            console.print(f"\n  Re-scoring [bold]{dossier.name}[/]…")
            new_score = _rescore(updated)

            ts = datetime.now(timezone.utc).isoformat()

            # Final decision — re-verified leads approved at lower bar (≥13)
            if new_score.combined_score >= _AUTO_APPROVE_THRESHOLD_P2:
                action = "approve"
                reason = (
                    f"APPROVE after re-research: {new_score.combined_score}/20 ≥ {_AUTO_APPROVE_THRESHOLD_P2} "
                    f"(post-verification gate). {new_score.reasoning}"
                )
                approvals.append(
                    FinalLead(
                        dossier=updated,
                        score=new_score.model_copy(update={"flag": "approve"}),
                        manager_reason=reason,
                    )
                )
            elif new_score.combined_score <= _AUTO_REJECT_THRESHOLD:
                action = "reject"
                reason = (
                    f"REJECT after re-research: {new_score.combined_score}/20 ≤ {_AUTO_REJECT_THRESHOLD}. "
                    f"Still below threshold after deeper look."
                )
            else:
                action = "reroute"
                reason = (
                    f"REROUTE: score {new_score.combined_score}/20 below verified gate "
                    f"({_AUTO_APPROVE_THRESHOLD_P2}) after re-research. "
                    f"Needs field verification: {follow_up}"
                )

            dec = ManagerDecision(
                business_name=dossier.name,
                action=action,
                reason=reason,
                follow_up_query=follow_up if action == "reroute" else None,
            )
            decisions.append(dec)
            print_manager_decision(dec)
            run_log.append(
                _log_entry(ts, updated, new_score, action, 2, reason, follow_up)
            )

        # ── STEP 5: top 5 approved ─────────────────────────────────────────────
        top5 = sorted(approvals, key=lambda l: l.score.combined_score, reverse=True)[:5]
        return top5, decisions, run_log


# ── helpers ────────────────────────────────────────────────────────────────────

def _log_entry(
    ts: str,
    dossier: BusinessDossier,
    score: LeadScore,
    action: str,
    pass_num: int,
    reason: str,
    follow_up: Optional[str] = None,
) -> dict:
    return {
        "timestamp":            ts,
        "pass":                 pass_num,
        "business_name":        dossier.name,
        "address":              dossier.address,
        "website":              dossier.website,
        "presence_gap_score":   score.presence_gap_score,
        "conversion_likelihood": score.conversion_likelihood,
        "combined_score":       score.combined_score,
        "primary_gap":          score.primary_gap,
        "flag":                 score.flag,
        "action":               action,
        "reason":               reason,
        "follow_up_query":      follow_up,
    }


# ── CrewAI agent wrapper (kept for full-crew pipeline) ─────────────────────────

def get_manager_agent(llm: "LLM") -> Agent:
    from pathlib import Path
    prompt = (Path(__file__).parents[2] / "prompts" / "manager.md").read_text()
    return Agent(
        role="Lead Intelligence Manager",
        goal=(
            "Orchestrate the research, scoring, and copywriting pipeline. "
            "Review scored leads and decide: approve, reject, or reroute for more research."
        ),
        backstory=prompt,
        tools=[],
        llm=llm,
        allow_delegation=True,
        verbose=True,
    )


# ── Stub fallback (backward compat) ───────────────────────────────────────────

def stub_decide(scores: list[LeadScore]) -> list[ManagerDecision]:
    """Deterministic stub — used only when RealManager is not wired."""
    actions = ["approve", "reject", "reroute"]
    decisions = []
    for i, score in enumerate(scores):
        action = actions[min(i, len(actions) - 1)]
        decisions.append(
            ManagerDecision(
                business_name=score.business_name,
                action=action,
                reason=(
                    f"Combined score {score.combined_score}/20 — {score.primary_gap}. "
                    + (
                        "Strong digital gap."
                        if action == "approve"
                        else "Below threshold." if action == "reject"
                        else "Borderline — needs more research."
                    )
                ),
                follow_up_query=(
                    f"Verify digital presence for {score.business_name}."
                    if action == "reroute"
                    else None
                ),
            )
        )
    return decisions
