"""Rich terminal UI for KĀRYO Agent."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from karyo.models.schemas import FinalLead, ManagerDecision

console = Console()

_AGENT_COLORS = {
    "Manager": "bold magenta",
    "Researcher": "bold cyan",
    "Scorer": "bold yellow",
    "Copywriter": "bold green",
}


def print_banner() -> None:
    console.print(
        Panel.fit(
            "[bold magenta]KĀRYO[/] [white]Lead Intelligence Agent[/]\n"
            "[dim]Agentathon 2026 — multi-agent lead generation[/]",
            border_style="magenta",
            padding=(1, 4),
        )
    )


def print_agent_start(agent_name: str) -> None:
    color = _AGENT_COLORS.get(agent_name, "bold white")
    console.print(
        Panel(
            f"[{color}]{agent_name}[/] is starting work…",
            title=f"[{color}]Agent[/]",
            border_style=color.split()[-1],
            expand=False,
        )
    )


def print_manager_decision(decision: ManagerDecision) -> None:
    action = decision.action
    color_map = {"approve": "green", "reject": "red", "reroute": "yellow"}
    icon_map = {"approve": "✓ APPROVE", "reject": "✗ REJECT", "reroute": "↺ REROUTE"}

    color = color_map[action]
    icon = icon_map[action]

    body = f"[bold]{decision.business_name}[/]\n{decision.reason}"
    if decision.follow_up_query:
        body += f"\n[dim]Follow-up: {decision.follow_up_query}[/]"

    console.print(
        Panel(
            body,
            title=f"[bold {color}]{icon}[/]",
            border_style=color,
            expand=False,
        )
    )


def print_final_table(leads: list[FinalLead]) -> None:
    top = sorted(leads, key=lambda l: l.score.combined_score, reverse=True)[:5]

    table = Table(
        title="[bold magenta]Top Approved Leads[/]",
        box=box.ROUNDED,
        show_lines=True,
        border_style="magenta",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Business", style="bold")
    table.add_column("Gap", justify="center")
    table.add_column("Conv", justify="center")
    table.add_column("Score", justify="center", style="bold yellow")
    table.add_column("Primary Gap", style="cyan")
    table.add_column("Flag", justify="center")

    flag_colors = {"approve": "green", "reject": "red", "borderline": "yellow"}

    for rank, lead in enumerate(top, 1):
        s = lead.score
        fc = flag_colors.get(s.flag, "white")
        table.add_row(
            str(rank),
            lead.dossier.name,
            str(s.presence_gap_score),
            str(s.conversion_likelihood),
            str(s.combined_score),
            s.primary_gap,
            f"[{fc}]{s.flag.upper()}[/]",
        )

    console.print()
    console.print(table)


def print_outputs_written(csv_path: str, email_count: int) -> None:
    console.print(
        Panel(
            f"[green]leads.csv[/]  →  {csv_path}\n"
            f"[green]{email_count} email(s)[/]  →  outputs/emails/",
            title="[bold green]Outputs Written[/]",
            border_style="green",
            expand=False,
        )
    )
