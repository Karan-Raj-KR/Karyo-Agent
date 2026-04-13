"""Manager agent — orchestrates the crew and makes approve/reject/reroute decisions."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from crewai import Agent

from karyo.models.schemas import LeadScore, ManagerDecision

if TYPE_CHECKING:
    from crewai import LLM

_PROMPT = (Path(__file__).parents[2] / "prompts" / "manager.md").read_text()


def get_manager_agent(llm: "LLM") -> Agent:
    return Agent(
        role="Lead Intelligence Manager",
        goal=(
            "Orchestrate the research, scoring, and copywriting pipeline. "
            "Review scored leads and decide: approve, reject, or reroute for more research."
        ),
        backstory=_PROMPT,
        tools=[],
        llm=llm,
        allow_delegation=True,
        verbose=True,
    )


# ---------------------------------------------------------------------------
# Stub — hardcoded 1 approve / 1 reject / 1 reroute pattern
# ---------------------------------------------------------------------------

def stub_decide(scores: list[LeadScore]) -> list[ManagerDecision]:
    """Return hardcoded decisions: approve first, reject second, reroute rest."""
    decisions: list[ManagerDecision] = []
    actions = ["approve", "reject", "reroute"]

    for i, score in enumerate(scores):
        action = actions[min(i, len(actions) - 1)]
        decision = ManagerDecision(
            business_name=score.business_name,
            action=action,
            reason=(
                f"Combined score {score.combined_score}/20 — {score.primary_gap}. "
                + (
                    "Strong digital gap; high priority lead."
                    if action == "approve"
                    else (
                        "Score below threshold; not worth the outreach cost."
                        if action == "reject"
                        else "Borderline score; send researcher back to check competitor landscape."
                    )
                )
            ),
            follow_up_query=(
                f"Research top 3 digital agencies already working with {score.business_name} competitors."
                if action == "reroute"
                else None
            ),
        )
        decisions.append(decision)

    return decisions
