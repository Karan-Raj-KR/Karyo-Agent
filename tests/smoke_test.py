"""Smoke test — runs the full stub pipeline and asserts outputs exist."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure KARYO_CACHE_ONLY is off so stub data is cached normally
os.environ["KARYO_CACHE_ONLY"] = "0"
os.environ.setdefault("KARYO_CACHE_DIR", "./cache")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from karyo.crew import KaryoCrew


def test_stub_pipeline() -> None:
    crew = KaryoCrew(city="Indiranagar", category="dentists")
    result = crew.kickoff()

    assert isinstance(result.final_leads, list), "final_leads must be a list"
    assert len(result.final_leads) >= 1, "At least 1 approved lead expected"
    assert isinstance(result.emails, dict), "emails must be a dict"

    # Write outputs (mirrors what agent.py does)
    import csv
    import re

    base = Path(__file__).parent.parent / "outputs"
    csv_path = base / "leads.csv"
    emails_dir = base / "emails"
    base.mkdir(exist_ok=True)
    emails_dir.mkdir(exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["name", "combined_score", "flag", "primary_gap"],
        )
        writer.writeheader()
        for lead in result.final_leads:
            writer.writerow(
                {
                    "name": lead.dossier.name,
                    "combined_score": lead.score.combined_score,
                    "flag": lead.score.flag,
                    "primary_gap": lead.score.primary_gap,
                }
            )

    assert csv_path.exists(), f"outputs/leads.csv not found at {csv_path}"
    print(f"[smoke_test] PASS — {len(result.final_leads)} lead(s), CSV at {csv_path}")


if __name__ == "__main__":
    test_stub_pipeline()
    sys.exit(0)
