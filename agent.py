"""
KĀRYO Lead Intelligence Agent — CLI entry point.

Usage:
    python agent.py --city "Indiranagar" --category "dentists"
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before any karyo imports (so env vars are visible to modules)
load_dotenv()


def _safe_filename(name: str) -> str:
    """Slugify a business name for use as a filename."""
    return re.sub(r"[^\w\-]", "_", name).lower()


def _write_csv(leads, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "name",
                "address",
                "phone",
                "website",
                "website_status",
                "has_ssl",
                "domain_age_years",
                "google_rating",
                "review_count",
                "presence_gap_score",
                "conversion_likelihood",
                "combined_score",
                "primary_gap",
                "flag",
                "manager_reason",
            ],
        )
        writer.writeheader()
        for lead in leads:
            d = lead.dossier
            s = lead.score
            writer.writerow(
                {
                    "name": d.name,
                    "address": d.address,
                    "phone": d.phone or "",
                    "website": d.website or "",
                    "website_status": d.website_status,
                    "has_ssl": d.has_ssl,
                    "domain_age_years": d.domain_age_years,
                    "google_rating": d.google_rating,
                    "review_count": d.review_count,
                    "presence_gap_score": s.presence_gap_score,
                    "conversion_likelihood": s.conversion_likelihood,
                    "combined_score": s.combined_score,
                    "primary_gap": s.primary_gap,
                    "flag": s.flag,
                    "manager_reason": lead.manager_reason,
                }
            )


def _write_emails(emails: dict[str, str], emails_dir: Path) -> None:
    emails_dir.mkdir(parents=True, exist_ok=True)
    for business_name, email_text in emails.items():
        filename = _safe_filename(business_name) + ".txt"
        (emails_dir / filename).write_text(email_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="karyo-agent",
        description="KĀRYO Lead Intelligence Agent — find and qualify local business leads.",
    )
    parser.add_argument("--city", required=True, help="City or neighbourhood to target")
    parser.add_argument("--category", required=True, help="Business category (e.g. dentists)")
    args = parser.parse_args()

    # Deferred imports so .env is loaded first
    from karyo.crew import KaryoCrew
    from karyo.ui.console import (
        print_banner,
        print_final_table,
        print_outputs_written,
        console,
    )

    print_banner()
    console.print(
        f"\n[bold]City:[/] {args.city}   [bold]Category:[/] {args.category}\n"
    )

    crew = KaryoCrew(city=args.city, category=args.category)
    result = crew.kickoff()

    # Write outputs
    base = Path(__file__).parent / "outputs"
    csv_path = base / "leads.csv"
    emails_dir = base / "emails"

    _write_csv(result.final_leads, csv_path)
    _write_emails(result.emails, emails_dir)

    # Write run_log.json
    log_path = base / "run_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(result.run_log, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Rich summary
    if result.final_leads:
        print_final_table(result.final_leads)
    else:
        console.print("[yellow]No approved leads this run.[/]")

    print_outputs_written(str(csv_path), len(result.emails))
    console.print(
        f"\n[dim]Mode: {result.mode} | "
        f"{len(result.final_leads)} approved lead(s) | "
        f"run_log → {log_path}[/]\n"
    )


if __name__ == "__main__":
    main()
