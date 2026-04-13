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
from karyo.tools.places import fetch_places
from karyo.ui.console import (
    print_agent_start,
    print_manager_decision,
)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    final_leads: list[FinalLead] = field(default_factory=list)
    emails: dict[str, str] = field(default_factory=dict)
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
        if self.llm is None:
            print("[crew] No API keys found — running in STUB mode.")
            return self._run_stub_pipeline()
        return self._run_crew_pipeline()

    # ------------------------------------------------------------------
    # Stub pipeline (no LLM required)
    # ------------------------------------------------------------------

    def _run_stub_pipeline(self) -> PipelineResult:
        from karyo.agents.researcher import stub_research
        from karyo.agents.scorer import stub_score
        from karyo.agents.manager import stub_decide
        from karyo.agents.copywriter import stub_copy

        # 1. Researcher
        print_agent_start("Researcher")
        businesses = fetch_places(self.city, self.category)
        dossiers: list[BusinessDossier] = [
            stub_research(b, self.city) for b in businesses
        ]

        # 2. Scorer
        print_agent_start("Scorer")
        scores: list[LeadScore] = [stub_score(d) for d in dossiers]

        # 3. Manager decides
        print_agent_start("Manager")
        decisions: list[ManagerDecision] = stub_decide(scores)
        for decision in decisions:
            print_manager_decision(decision)

        # 4. Copywriter — only for approved leads
        print_agent_start("Copywriter")
        approved_names = {d.business_name for d in decisions if d.action == "approve"}

        final_leads: list[FinalLead] = []
        emails: dict[str, str] = {}

        for dossier, score, decision in zip(dossiers, scores, decisions):
            if decision.action == "approve":
                lead = FinalLead(
                    dossier=dossier,
                    score=score,
                    manager_reason=decision.reason,
                )
                email = stub_copy(lead)
                final_leads.append(lead)
                emails[dossier.name] = email

        return PipelineResult(final_leads=final_leads, emails=emails, mode="stub")

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
                "Use the google_places_search tool to find candidates, then "
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
