# KĀRYO Lead Intelligence Agent

Multi-agent system for local business lead generation — built for **Agentathon 2026**.

## Stack
- **CrewAI** (hierarchical process) — agent orchestration
- **Groq** `llama-3.3-70b-versatile` — primary LLM (OpenAI fallback)
- **Pydantic v2** — data models
- **diskcache** — persistent caching for every external call
- **rich** — terminal UI

## Quick start

```bash
# 1. Install dependencies
uv sync

# 2. Configure credentials
cp .env.example .env
# Edit .env — add GROQ_API_KEY at minimum

# 3. Run
python agent.py --city "Indiranagar" --category "dentists"
```

If no API keys are set the pipeline runs in **stub mode** (hardcoded dummy data) so you can verify the scaffold end-to-end immediately.

## Outputs

| File | Description |
|------|-------------|
| `outputs/leads.csv` | All approved leads with scores |
| `outputs/emails/<name>.txt` | Personalised outreach email per lead |

## Architecture

```
agent.py  →  KaryoCrew.kickoff()
               │
               ├── Researcher  (Places + Website + WHOIS tools)
               ├── Scorer      (gap + conversion scoring)
               ├── Manager     (approve / reject / reroute)
               └── Copywriter  (personalised email per lead)
```

## Smoke test

```bash
python tests/smoke_test.py
```
