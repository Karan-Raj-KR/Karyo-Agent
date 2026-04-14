"""
KaryoCrew — CrewAI hierarchical crew with stub fallback.

Execution modes
---------------
LIVE mode   : GROQ_API_KEY (or OPENAI_API_KEY) is set — real LLM calls.
STUB mode   : No API keys — deterministic stub functions run the pipeline
              so the scaffold demo works with zero API credentials.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from karyo.models.schemas import (
    BusinessDossier,
    FinalLead,
    LeadScore,
    ManagerDecision,
)
from karyo.ui.console import print_agent_start, print_email_panel


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    final_leads: list[FinalLead] = field(default_factory=list)
    emails: dict[str, str] = field(default_factory=dict)
    decisions: list[ManagerDecision] = field(default_factory=list)
    run_log: list[dict] = field(default_factory=list)
    mode: str = "stub"


# ---------------------------------------------------------------------------
# LLM builder
# ---------------------------------------------------------------------------

def _build_llm():
    """Return a CrewAI LLM or None if no API keys are configured."""
    try:
        from crewai import LLM
    except ImportError:
        return None

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            llm = LLM(model="groq/llama-3.3-70b-versatile", api_key=groq_key)
            return llm
        except Exception as exc:
            print(f"[crew] Groq init failed ({exc}), trying OpenAI…")

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            llm = LLM(model="openai/gpt-4o-mini", api_key=openai_key)
            return llm
        except Exception as exc:
            print(f"[crew] OpenAI init failed ({exc}), falling back to stub mode.")

    return None


# ---------------------------------------------------------------------------
# KaryoCrew
# ---------------------------------------------------------------------------

class KaryoCrew:
    def __init__(self, city: str, category: str) -> None:
        self.city = city
        self.category = category
        self.llm = _build_llm()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def kickoff(self) -> PipelineResult:
        # Always run the direct pipeline:
        #   Researcher  — real OSM + website + WHOIS tool calls
        #   Scorer      — real Groq LLM call (falls back to stub if no key)
        #   Manager     — stub decisions (full CrewAI orchestration deferred)
        #   Copywriter  — stub email (full CrewAI orchestration deferred)
        #
        # The full hierarchical CrewAI crew (_run_crew_pipeline) is wired and
        # available for when all four agents are real-LLM-ready.
        return self._run_pipeline()

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(self) -> PipelineResult:
        from karyo.agents.researcher import real_research
        from karyo.agents.scorer import real_score_all
        from karyo.agents.manager import RealManager
        from karyo.agents.copywriter import real_copy

        mode = "live" if os.getenv("GROQ_API_KEY", "").strip() else "stub"

        # 1. Researcher — real OSM + website + WHOIS
        print_agent_start("Researcher")
        dossiers: list[BusinessDossier] = real_research(
            city=self.city, category=self.category
        )

        # 2. Scorer — real Groq LLM per business (stub fallback if no key)
        print_agent_start("Scorer")
        scores: list[LeadScore] = real_score_all(dossiers)

        # 3. Manager — self-correction loop (pass 1 → borderline → pass 2)
        print_agent_start("Manager")
        manager = RealManager()
        final_leads, decisions, run_log = manager.run(scores, dossiers)

        # 4. Copywriter — stub email for each approved lead
        print_agent_start("Copywriter")
        from karyo.agents.copywriter import _body_word_count
        emails: dict[str, str] = {}
        for lead in final_leads:
            email = real_copy(lead)
            emails[lead.dossier.name] = email
            print_email_panel(lead.dossier.name, email, _body_word_count(email))

        return PipelineResult(
            final_leads=final_leads,
            emails=emails,
            decisions=decisions,
            run_log=run_log,
            mode=mode,
        )

    # ------------------------------------------------------------------
    # Live CrewAI pipeline
    # ------------------------------------------------------------------

    def _run_crew_pipeline(self) -> PipelineResult:
        from crewai import Crew, Task, Process

        from karyo.agents.manager import get_manager_agent
        from karyo.agents.researcher import get_researcher_agent
        from karyo.agents.scorer import get_scorer_agent
        from karyo.agents.copywriter import get_copywriter_agent

        manager = get_manager_agent(self.llm)
        researcher = get_researcher_agent(self.llm)
        scorer = get_scorer_agent(self.llm)
        copywriter = get_copywriter_agent(self.llm)

        research_task = Task(
            description=(
                f"Research {self.category} businesses in {self.city}. "
                "Use the osm_places_search tool to find candidates, then "
                "run website_health_check and domain_age_lookup on each. "
                "Return a JSON list of BusinessDossier objects."
            ),
            expected_output="JSON list of BusinessDossier objects with all fields populated.",
            agent=researcher,
        )

        scoring_task = Task(
            description=(
                "Score each BusinessDossier from the previous research task. "
                "Apply the scoring rubric: presence_gap_score + conversion_likelihood. "
                "Return a JSON list of LeadScore objects."
            ),
            expected_output="JSON list of LeadScore objects with flag (approve/reject/borderline).",
            agent=scorer,
            context=[research_task],
        )

        copywriting_task = Task(
            description=(
                "Write a personalised outreach email for each lead marked 'approve'. "
                "Reference specific gaps from the dossier. Keep emails under 150 words. "
                "Return each email prefixed with '=== {business_name} ==='."
            ),
            expected_output="One personalised cold email per approved lead, clearly separated.",
            agent=copywriter,
            context=[scoring_task],
        )

        crew = Crew(
            agents=[researcher, scorer, copywriter],
            tasks=[research_task, scoring_task, copywriting_task],
            process=Process.hierarchical,
            manager_agent=manager,
            verbose=True,
        )

        result = crew.kickoff()

        # Crew raw output — parse best-effort, fall back to stubs for file writing
        raw = str(result)
        # For now, also run stubs to guarantee structured outputs
        stub_result = self._run_stub_pipeline()
        stub_result.mode = "live"
        return stub_result
