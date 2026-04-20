# KĀRYO Agent Architecture

## System Flowchart

```mermaid
flowchart TD
    CLI["⌨️ CLI Entry\nagent.py\n--city / --category"]
    Crew["KaryoCrew.kickoff()"]

    subgraph R["🔍 RESEARCHER AGENT"]
        R1["fetch_places()\nOpenStreetMap Nominatim + Overpass"]
        R2["check_website()\nHTTP · SSL · response time"]
        R3["domain_age_lookup()\nWHOIS"]
        R4["BusinessDossier\n(name, address, phone, website,\nwebsite_status, has_ssl,\ndomain_age_years, review_count)"]
        R1 --> R2 --> R3 --> R4
    end

    subgraph SC["📊 SCORER AGENT"]
        S1["Groq llama-3.3-70b-versatile\n+ 2-turn JSON retry"]
        S2["presence_gap_score\n(1–10)\nhow broken the digital presence is"]
        S3["conversion_likelihood\n(1–10)\nhow likely they'll pay for help"]
        S4["combined_score = gap + likelihood\nflag: approve / reject / borderline"]
        S1 --> S2
        S1 --> S3
        S2 --> S4
        S3 --> S4
    end

    subgraph MG["🧠 MANAGER AGENT — 2-Pass Self-Correction"]
        M1["PASS 1\nFirst-Cut Decisions"]
        MA["combined ≥ 16\n✅ AUTO-APPROVE"]
        MR["combined ≤ 8\n❌ AUTO-REJECT"]
        MB["combined 9–15\n⏳ BORDERLINE"]

        M1 --> MA
        M1 --> MR
        M1 --> MB

        subgraph P2["PASS 2 — Borderline Re-evaluation"]
            P2A["① Groq generates\nfollow-up research query"]
            P2B["② Re-research dossier\n(website recheck + query appended)"]
            P2C["③ Re-score with Scorer\n(fresh LLM evaluation)"]
            P2D{"re-score threshold"}
            P2E["≥ 13 → ✅ APPROVE"]
            P2F["9–12 → ↺ REROUTE"]
            P2G["≤ 8 → ❌ REJECT"]
            P2A --> P2B --> P2C --> P2D
            P2D --> P2E
            P2D --> P2F
            P2D --> P2G
        end

        MB --> P2A
        MA --> FINAL
        P2E --> FINAL
        FINAL["🏆 Top 5 FinalLeads\n(ranked by combined_score)"]
    end

    subgraph CW["✍️ COPYWRITER AGENT"]
        CW1["Groq llama-3.3-70b-versatile\n10 hard email rules via system prompt"]
        CW2["Word-count check\n100–140 words"]
        CW3{"in range?"}
        CW4["✅ Accept email"]
        CW5["Retry with direction\n(shorter / longer)"]
        CW1 --> CW2 --> CW3
        CW3 -- "yes" --> CW4
        CW3 -- "no" --> CW5 --> CW4
    end

    subgraph CACHE["💾 CACHE LAYER (diskcache / SQLite)"]
        C1["places_v2 + city + category"]
        C2["website_v2 + url"]
        C3["whois_v2 + domain"]
        C4["llm_score_v1 + name + dossier_json"]
        C5["manager_followup_v1 + name + score + gap"]
        C6["copywriter_v3 + name + primary_gap"]
    end

    subgraph OUT["📂 OUTPUTS"]
        O1["outputs/leads.csv\nScored, ranked leads"]
        O2["outputs/emails/*.txt\n1 email per lead"]
        O3["outputs/run_log.json\nFull audit trail"]
    end

    CLI --> Crew --> R
    R4 --> SC
    S4 --> MG
    FINAL --> CW
    CW4 --> OUT
    FINAL --> O1
    FINAL --> O3
    CW4 --> O2

    R1 -.->|cached| C1
    R2 -.->|cached| C2
    R3 -.->|cached| C3
    S1 -.->|cached| C4
    P2A -.->|cached| C5
    CW1 -.->|cached| C6
```

---

## Decision Thresholds

```
PASS 1                          PASS 2
──────────────────────          ──────────────────────
combined ≥ 16 → APPROVE         re-score ≥ 13 → APPROVE
combined ≤ 8  → REJECT          re-score ≤ 8  → REJECT
combined 9–15 → BORDERLINE →→→  re-score 9–12 → REROUTE
                (enters Pass 2)
```

The lower Pass 2 threshold (13 vs 16) **rewards the extra research effort** — a borderline lead that survives re-evaluation has earned its approval.

---

## Data Flow Summary

```
CLI args
  └─▶ Researcher ──▶ list[BusinessDossier]
         └─▶ Scorer ──▶ list[LeadScore]  (flag: approve/reject/borderline)
               └─▶ Manager
                     ├─ Pass 1 → clear decisions
                     └─ Pass 2 → re-research + re-score borderlines
                           └─▶ list[FinalLead]  (top 5)
                                 └─▶ Copywriter ──▶ dict[name → email]
                                       └─▶ Write outputs
                                             ├─ leads.csv
                                             ├─ emails/*.txt
                                             └─ run_log.json
```
