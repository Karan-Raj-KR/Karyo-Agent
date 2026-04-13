"""
Standalone integration test for the Overpass + website + whois tools.

Run from the karyo-agent/ root:
    uv run python scripts/test_places.py

What it does:
  1. Fetches dentists in Indiranagar via Overpass API (live network call)
  2. Prints name / address / website for each result
  3. Checks website health for the first result that has a URL
  4. Checks domain age for the same URL
  5. Runs the SAME calls again — shows cache HIT (sub-millisecond)
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Make sure karyo package is importable when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s — %(message)s",
)

from karyo.tools.places import fetch_places
from karyo.tools.website import check_website
from karyo.tools.whois_tool import get_domain_age


SEP = "─" * 60


def hdr(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def timed(label: str, fn, *args):
    t0 = time.perf_counter()
    result = fn(*args)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  ⏱  {label}: {elapsed:.1f} ms")
    return result


# ─────────────────────────────────────────────────────────
# RUN 1 — live (or populate cache on first ever run)
# ─────────────────────────────────────────────────────────
hdr("RUN 1 — Overpass: dentists in Indiranagar (network)")

places = timed("fetch_places()", fetch_places, "Indiranagar", "dentists")

if not places:
    print("\n  ⚠  No results returned from Overpass.")
    print("     This can happen if Indiranagar isn't mapped with place=suburb in OSM,")
    print("     or if the API is temporarily unavailable.")
    print("     The second run will demonstrate cache (miss → miss is still instant).\n")
else:
    print(f"\n  Found {len(places)} result(s):\n")
    for i, p in enumerate(places, 1):
        print(f"  [{i}] {p['name']}")
        print(f"      Address : {p['address']}")
        print(f"      Phone   : {p.get('phone') or '—'}")
        print(f"      Website : {p.get('website') or '—'}")
        print(f"      Coords  : {p['lat']}, {p['lng']}")
        print()

# Website + WHOIS for first result with a URL
target_url: str | None = None
for p in places:
    if p.get("website"):
        target_url = p["website"]
        print(f"  Checking website: {target_url}")
        health = timed("check_website()", check_website, target_url)
        print(f"  → status={health.status}  ssl={health.has_ssl}  "
              f"time={health.response_time_ms}ms  mobile={health.mobile_meta_tag}")

        from urllib.parse import urlparse
        domain = urlparse(target_url).netloc or target_url
        print(f"\n  Checking WHOIS: {domain}")
        age = timed("get_domain_age()", get_domain_age, domain)
        print(f"  → domain age: {age} yr")
        break

if target_url is None:
    print("  (no websites in results — skipping health + WHOIS check)")


# ─────────────────────────────────────────────────────────
# RUN 2 — must be a cache HIT (instant)
# ─────────────────────────────────────────────────────────
hdr("RUN 2 — same calls (should be cache HIT, sub-5ms each)")

places2 = timed("fetch_places() cached", fetch_places, "Indiranagar", "dentists")
assert places2 == places, "Cache returned different data!"
print(f"  ✓ Same {len(places2)} result(s) returned from cache")

if target_url:
    health2 = timed("check_website() cached", check_website, target_url)
    assert health2.status == health.status
    print(f"  ✓ Website health cached: {health2.status}")

    from urllib.parse import urlparse
    domain = urlparse(target_url).netloc or target_url
    age2 = timed("get_domain_age() cached", get_domain_age, domain)
    assert age2 == age
    print(f"  ✓ Domain age cached: {age2} yr")

print(f"\n{SEP}")
print("  ALL CHECKS PASSED")
print(SEP + "\n")
