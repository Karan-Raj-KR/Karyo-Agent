"""
Overpass API (OpenStreetMap) places tool — no API key required.

Strategy
--------
1. Geocode city/neighbourhood via Nominatim → get bounding box (cached).
2. Run a bbox Overpass query (fast, never times out on large areas).
3. Fall back to area-name Overpass query if Nominatim fails.
4. Cache results (including empty list) so second run is instant.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from karyo.cache.store import get_store

log = logging.getLogger(__name__)

OVERPASS_URL   = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL  = "https://nominatim.openstreetmap.org/search"
OVERPASS_TIMEOUT  = 30   # seconds — per request
NOMINATIM_TIMEOUT = 10

# Use multiple public Overpass mirrors in case primary is overloaded
_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

_HEADERS = {"User-Agent": "KaryoAgent/0.1 (hackathon; contact@karyo.in)"}

# ---------------------------------------------------------------------------
# Category → OSM tag mapping
# ---------------------------------------------------------------------------
_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "dentist":        ("amenity", "dentist"),
    "dentists":       ("amenity", "dentist"),
    "restaurant":     ("amenity", "restaurant"),
    "restaurants":    ("amenity", "restaurant"),
    "cafe":           ("amenity", "cafe"),
    "cafes":          ("amenity", "cafe"),
    "clinic":         ("amenity", "clinic"),
    "clinics":        ("amenity", "clinic"),
    "hospital":       ("amenity", "hospital"),
    "hospitals":      ("amenity", "hospital"),
    "pharmacy":       ("amenity", "pharmacy"),
    "pharmacies":     ("amenity", "pharmacy"),
    "gym":            ("leisure", "fitness_centre"),
    "gyms":           ("leisure", "fitness_centre"),
    "fitness":        ("leisure", "fitness_centre"),
    "salon":          ("shop", "hairdresser"),
    "salons":         ("shop", "hairdresser"),
    "hairdresser":    ("shop", "hairdresser"),
    "barber":         ("shop", "barber"),
    "bakery":         ("shop", "bakery"),
    "bakeries":       ("shop", "bakery"),
    "supermarket":    ("shop", "supermarket"),
    "hotel":          ("tourism", "hotel"),
    "hotels":         ("tourism", "hotel"),
    "school":         ("amenity", "school"),
    "bank":           ("amenity", "bank"),
    "banks":          ("amenity", "bank"),
}

# Bbox: (south, west, north, east)
Bbox = tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# Nominatim geocoding (cached)
# ---------------------------------------------------------------------------

def _geocode(place: str) -> Optional[Bbox]:
    """Return (south, west, north, east) bounding box or None."""
    store = get_store()
    cache_key = store.make_key("nominatim_bbox", place.lower())
    cached = store.get(cache_key)
    if cached is not None:
        log.info("nominatim cache HIT  %s", place)
        return tuple(cached) if cached else None   # type: ignore[return-value]

    log.info("nominatim cache MISS — geocoding '%s'", place)
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": place, "format": "json", "limit": 1, "addressdetails": 1},
            timeout=NOMINATIM_TIMEOUT,
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Nominatim request failed for '%s': %s", place, exc)
        store.set(cache_key, None)
        return None

    if not data:
        log.warning("Nominatim found no results for '%s'", place)
        store.set(cache_key, None)
        return None

    bb = data[0].get("boundingbox")   # [south_str, north_str, west_str, east_str]
    if not bb or len(bb) < 4:
        store.set(cache_key, None)
        return None

    bbox: Bbox = (float(bb[0]), float(bb[2]), float(bb[1]), float(bb[3]))
    log.info("Nominatim bbox for '%s': %s", place, bbox)
    store.set(cache_key, list(bbox))
    return bbox


# ---------------------------------------------------------------------------
# Overpass query builders
# ---------------------------------------------------------------------------

def _bbox_query(bbox: Bbox, tag_key: str, tag_value: str) -> str:
    s, w, n, e = bbox
    return (
        f"[out:json][timeout:25];\n"
        f"(\n"
        f'  node["{tag_key}"="{tag_value}"]({s},{w},{n},{e});\n'
        f'  way["{tag_key}"="{tag_value}"]({s},{w},{n},{e});\n'
        f");\n"
        f"out body center;\n"   # "center" adds lat/lon for ways
    )


def _area_query(city: str, tag_key: str, tag_value: str) -> str:
    """Fallback area-name query (may 504 on large/ambiguous areas)."""
    place_types = ["suburb", "neighbourhood", "village", "town", "city", "district"]
    selectors = "\n  ".join(
        f'area["name"="{city}"]["place"="{pt}"];' for pt in place_types
    )
    return (
        f"[out:json][timeout:25];\n"
        f"(\n  {selectors}\n)->.a;\n"
        f"(\n"
        f'  node["{tag_key}"="{tag_value}"](area.a);\n'
        f'  way["{tag_key}"="{tag_value}"](area.a);\n'
        f");\n"
        f"out body center;\n"
    )


def _name_bbox_query(bbox: Bbox, category: str) -> str:
    """For unknown categories, search by name keyword within bbox."""
    s, w, n, e = bbox
    return (
        f"[out:json][timeout:25];\n"
        f"(\n"
        f'  node["name"~"{category}",i]({s},{w},{n},{e});\n'
        f'  way["name"~"{category}",i]({s},{w},{n},{e});\n'
        f");\n"
        f"out body center;\n"
    )


# ---------------------------------------------------------------------------
# Overpass HTTP caller with mirror fallback
# ---------------------------------------------------------------------------

def _run_overpass(query: str) -> Optional[list[dict]]:
    """Try each Overpass mirror in turn. Return elements list or None."""
    for mirror in _OVERPASS_MIRRORS:
        try:
            resp = requests.post(
                mirror,
                data={"data": query},
                timeout=OVERPASS_TIMEOUT,
                headers=_HEADERS,
            )
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            log.info("Overpass success via %s (%d elements)", mirror, len(elements))
            return elements
        except requests.exceptions.Timeout:
            log.warning("Overpass timeout on %s — trying next mirror", mirror)
        except requests.exceptions.RequestException as exc:
            log.warning("Overpass error on %s: %s — trying next mirror", mirror, exc)
        except Exception as exc:
            log.warning("Overpass parse error on %s: %s", mirror, exc)

    log.error("All Overpass mirrors failed")
    return None


# ---------------------------------------------------------------------------
# OSM element → normalised dict
# ---------------------------------------------------------------------------

def _extract_address(tags: dict[str, str], city: str) -> str:
    if tags.get("addr:full"):
        return tags["addr:full"]

    parts: list[str] = []
    housenumber = tags.get("addr:housenumber", "").strip()
    street = tags.get("addr:street", "").strip()
    suburb = tags.get("addr:suburb", tags.get("addr:neighbourhood", "")).strip()
    postcode = tags.get("addr:postcode", "").strip()

    if housenumber and street:
        parts.append(f"{housenumber}, {street}")
    elif street:
        parts.append(street)
    if suburb:
        parts.append(suburb)
    parts.append(city)
    if postcode:
        parts.append(postcode)

    return ", ".join(parts)


def _parse_elements(elements: list[dict], city: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("brand") or tags.get("operator")
        if not name or name in seen:
            continue
        seen.add(name)

        # Coordinates: nodes have lat/lon; ways have a "center" key (with "out center")
        lat = el.get("lat") or el.get("center", {}).get("lat", 0.0)
        lon = el.get("lon") or el.get("center", {}).get("lon", 0.0)

        phone = (
            tags.get("phone")
            or tags.get("contact:phone")
            or tags.get("telephone")
        )
        website = (
            tags.get("website")
            or tags.get("contact:website")
            or tags.get("url")
        )
        if website and not website.startswith(("http://", "https://")):
            website = "http://" + website

        results.append({
            "name": name,
            "place_id": f"osm:{el.get('type','n')}{el.get('id', 0)}",
            "address": _extract_address(tags, city),
            "phone": phone,
            "website": website,
            "lat": lat,
            "lng": lon,
            "google_rating": None,
            "review_count": 0,
        })

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_places(city: str, category: str) -> list[dict[str, Any]]:
    """
    Query Overpass for businesses matching *category* in *city*.

    Returns a list of normalised dicts (possibly empty). Never raises.
    Cached via diskcache — second call is instant.
    """
    store = get_store()
    cache_key = store.make_key("places_v2", city.lower(), category.lower())

    cached = store.get(cache_key)
    if cached is not None:
        log.info("places cache HIT  (%s / %s) → %d result(s)", city, category, len(cached))
        return cached

    log.info("places cache MISS — fetching (%s / %s)", city, category)

    # Resolve tag
    norm = category.lower().strip()
    tag_key, tag_value = _CATEGORY_MAP.get(norm, ("name", norm))
    is_tag_search = norm in _CATEGORY_MAP

    # Step 1 — Nominatim bbox
    bbox = _geocode(city)

    elements: Optional[list[dict]] = None

    if bbox is not None:
        if is_tag_search:
            query = _bbox_query(bbox, tag_key, tag_value)
        else:
            query = _name_bbox_query(bbox, category)
        elements = _run_overpass(query)
    else:
        log.info("Nominatim failed — falling back to Overpass area query")

    # Step 2 — area-name fallback if bbox failed or gave nothing
    if (elements is None or len(elements) == 0) and is_tag_search:
        log.info("Trying area-name Overpass fallback for '%s'", city)
        fallback = _area_query(city, tag_key, tag_value)
        elements2 = _run_overpass(fallback)
        if elements2:
            elements = elements2

    # On complete failure don't cache — let next run retry
    if elements is None:
        log.error("All lookup strategies failed for (%s / %s)", city, category)
        return []

    results = _parse_elements(elements, city)
    store.set(cache_key, results)   # cache even [] so next call is instant
    log.info("Stored %d result(s) in cache for (%s / %s)", len(results), city, category)
    return results


# ---------------------------------------------------------------------------
# CrewAI Tool wrapper
# ---------------------------------------------------------------------------

class PlacesInput(BaseModel):
    city: str = Field(description="City or neighbourhood to search (e.g. 'Indiranagar')")
    category: str = Field(description="Business category (e.g. 'dentists', 'restaurants')")


class PlacesTool(BaseTool):
    name: str = "osm_places_search"
    description: str = (
        "Search for local businesses using OpenStreetMap / Overpass API (free, no key). "
        "Returns name, address, phone, website, and GPS coordinates."
    )
    args_schema: Type[BaseModel] = PlacesInput

    def _run(self, city: str, category: str) -> str:
        businesses = fetch_places(city, category)
        return json.dumps(businesses, indent=2, ensure_ascii=False)
