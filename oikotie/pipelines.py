"""Per-pipeline business logic: geocode/filter/score/rank/dedupe, and the
per-listing risk-flag heuristics shown on report cards.

Behavior mirrors the original monolithic main(): same thresholds, same
_search_pass tagging, same tiering/sort order — only reorganized so each
pipeline's rules live in one place instead of inlined across a 2,000-line
function.
"""

import re
import time

from oikotie.config import (
    HELSINKI_CENTRAL_COORDS, MAX_STOP_DIST_M, NEWBUILD_TOP_N,
)
from oikotie.geo import geocode_address, haversine_m, nearest_hub, nearest_mall, nearest_tram_stop
from oikotie.parsing import _eval_pipe_done
from oikotie.scoring import (
    _effective_price, _loan_acceptable, monthly_cost_eur, score_listing,
    score_uusimaa_listing,
)

_PKS_GEO_FIELDS = ("lat", "lon", "nearest_hub", "hub_distance_m",
                   "nearest_mall", "mall_distance_m", "helsinki_central_km", "tram_badge")


# ---------------------------------------------------------------------------
# Geocoding (mutates cache/geo_cache in place; caller persists them to disk)
# ---------------------------------------------------------------------------

def geocode_tram_listings(listings: list[dict], cache: dict, geo_cache: dict) -> list[dict]:
    """Geocode tram-corridor listings and keep only those within MAX_STOP_DIST_M."""
    geocoded: list[dict] = []
    fresh = 0
    print(f"\n  Geocoding {len(listings)} tram listings (≤{MAX_STOP_DIST_M} m from stop) …")
    for listing in listings:
        url  = listing.get("listing_url", "")
        addr = listing.get("address", "")
        city = listing.get("city", "")
        if url and url in cache and cache[url].get("lat") is not None:
            entry = cache[url]
            listing.update({k: entry[k] for k in ("lat", "lon", "nearest_stop", "distance_m") if k in entry})
            if listing.get("distance_m", 9999) <= MAX_STOP_DIST_M:
                geocoded.append(listing)
            continue
        was_cached = f"{addr}, {city}, Finland" in geo_cache
        coords = geocode_address(addr, city, geo_cache)
        if not was_cached:
            fresh += 1
            time.sleep(1.5)
        if coords is None:
            listing.update({"lat": None, "lon": None, "nearest_stop": None, "distance_m": None})
            geocoded.append(listing)
            continue
        lat, lon = coords
        stop_name, dist_m = nearest_tram_stop(lat, lon)
        geo_fields = {
            "lat": round(lat, 6), "lon": round(lon, 6),
            "nearest_stop": stop_name, "distance_m": round(dist_m),
        }
        listing.update(geo_fields)
        if url and url in cache:
            cache[url].update(geo_fields)  # persist so next run skips Nominatim
        if dist_m <= MAX_STOP_DIST_M:
            geocoded.append(listing)

    print(f"  {fresh} fresh geocodes, {len(listings)-fresh} from cache")
    print(f"  Within {MAX_STOP_DIST_M} m of a stop: {len(geocoded)}/{len(listings)}")
    return geocoded


def _geocode_pks_listing(listing: dict, cache: dict, geo_cache: dict) -> tuple[bool, bool]:
    """Geocode one PKS (Uusimaa/newbuild) listing in place.

    Returns (geocoded, was_fresh) — was_fresh is True only when a live
    Nominatim lookup was made (neither the listing cache nor the geocode
    cache already had it)."""
    url  = listing.get("listing_url", "")
    addr = listing.get("address", "")
    city = listing.get("city", "")
    if url and url in cache and cache[url].get("lat") is not None:
        entry = cache[url]
        listing.update({k: entry[k] for k in _PKS_GEO_FIELDS if k in entry})
        return True, False
    was_cached = f"{addr}, {city}, Finland" in geo_cache
    coords = geocode_address(addr, city, geo_cache)
    if coords is None:
        return False, not was_cached
    if not was_cached:
        time.sleep(1.5)
    lat, lon = coords
    hub_name,  hub_dist  = nearest_hub(lat, lon)
    mall_name, mall_dist = nearest_mall(lat, lon)
    hc_km = haversine_m(lat, lon, HELSINKI_CENTRAL_COORDS[0], HELSINKI_CENTRAL_COORDS[1]) / 1000
    tram_name, tram_dist = nearest_tram_stop(lat, lon)
    tram_badge = {"stop": tram_name, "dist": round(tram_dist)} if tram_dist <= MAX_STOP_DIST_M else None
    geo_fields = {
        "lat":                 round(lat, 6),
        "lon":                 round(lon, 6),
        "nearest_hub":         hub_name,
        "hub_distance_m":      round(hub_dist),
        "nearest_mall":        mall_name,
        "mall_distance_m":     round(mall_dist),
        "helsinki_central_km": round(hc_km, 2),
        "tram_badge":          tram_badge,
    }
    listing.update(geo_fields)
    if url and url in cache:
        cache[url].update(geo_fields)  # persist so next run skips Nominatim
    return True, not was_cached


def geocode_uusimaa_listings(listings: list[dict], cache: dict, geo_cache: dict) -> list[dict]:
    geocoded: list[dict] = []
    fresh = 0
    print(f"  Geocoding {len(listings)} PKS listings …")
    for listing in listings:
        ok, was_fresh = _geocode_pks_listing(listing, cache, geo_cache)
        if ok:
            geocoded.append(listing)
        if was_fresh:
            fresh += 1
    print(f"  {fresh} fresh geocodes, {len(listings)-fresh} from cache")
    return geocoded


# ---------------------------------------------------------------------------
# Tram pipeline: classify + score + rank
# ---------------------------------------------------------------------------

def classify_tram(geocoded: list[dict], price_max: float, loan_ratio_max: float) -> tuple[list[dict], list[dict]]:
    confirmed: list[dict] = []
    candidates: list[dict] = []
    for l in geocoded:
        if _effective_price(l) > price_max:
            continue
        if not _loan_acceptable(l, loan_ratio_max):
            continue
        year      = l.get("year_built") or 0
        is_old    = (l.get("year_built") or 9999) < 2000
        pipe_done = _eval_pipe_done(l.get("pipe_renovation_info"), l.get("pipe_renovation_year"))
        if 1980 <= year <= 1995 and not pipe_done:
            continue
        if not is_old:
            l["_search_pass"] = "new_house_2000plus"
            confirmed.append(l)
        elif pipe_done:
            l["_search_pass"] = f"pipe_reno_{l.get('pipe_renovation_year') or 'done'}"
            confirmed.append(l)
        else:
            l["_search_pass"] = "candidate_check_pipe_reno"
            candidates.append(l)
    return confirmed, candidates


def _tram_tier(l: dict) -> int:
    if l.get("is_rented_out"):                                    return 0
    if l.get("_search_pass") == "new_house_2000plus":              return 1
    if (l.get("_search_pass") or "").startswith("pipe_reno_"):     return 2
    return 3


def score_and_rank_tram(confirmed: list[dict], candidates: list[dict]) -> list[dict]:
    """Score, rank, and sort confirmed/candidates in place. Returns rented-out subset."""
    for l in confirmed + candidates:
        l["monthly_cost_eur"] = round(monthly_cost_eur(l), 2)
        l["score"]            = score_listing(l)

    all_tram = confirmed + candidates
    all_tram.sort(key=lambda l: (_tram_tier(l), -l["score"]))
    for rank, l in enumerate(all_tram, 1):
        l["rank"] = rank
    confirmed.sort(key=lambda l: -l["score"])
    candidates.sort(key=lambda l: -l["score"])
    return [l for l in all_tram if l.get("is_rented_out")]


# ---------------------------------------------------------------------------
# Uusimaa (PKS) pipeline: pre-filter + classify + score + rank
# ---------------------------------------------------------------------------

def prefilter_uusimaa(listings: list[dict], price_max: float, loan_ratio_max: float) -> list[dict]:
    """Price/loan/pipe pre-filter, applied before the (costly) geocoding step."""
    kept: list[dict] = []
    for l in listings:
        if _effective_price(l) > price_max:
            continue
        if not _loan_acceptable(l, loan_ratio_max):
            continue
        year      = l.get("year_built") or 0
        pipe_done = _eval_pipe_done(l.get("pipe_renovation_info"), l.get("pipe_renovation_year"))
        if 1980 <= year <= 1995 and not pipe_done:
            continue
        kept.append(l)
    print(f"\n  Pre-filter (price/loan/pipe): {len(listings)} → {len(kept)} listings to geocode")
    return kept


def score_and_rank_uusimaa(geocoded: list[dict], top_unrented: int) -> tuple[list[dict], list[dict], list[dict]]:
    passing: list[dict] = []
    for l in geocoded:
        is_old    = (l.get("year_built") or 9999) < 2000
        pipe_done = _eval_pipe_done(l.get("pipe_renovation_info"), l.get("pipe_renovation_year"))
        if not is_old:
            l["_search_pass"] = "new_house_2000plus"
        elif pipe_done:
            l["_search_pass"] = f"pipe_reno_{l.get('pipe_renovation_year') or 'done'}"
        else:
            l["_search_pass"] = "candidate_check_pipe_reno"
        l["monthly_cost_eur"] = round(monthly_cost_eur(l), 2)
        l["score"] = score_uusimaa_listing(l)
        passing.append(l)

    passing.sort(key=lambda l: -l["score"])
    for rank, l in enumerate(passing, 1):
        l["rank"] = rank
    rented = [l for l in passing if l.get("is_rented_out")]
    top5   = [l for l in passing if not l.get("is_rented_out")][:top_unrented]
    return passing, rented, top5


# ---------------------------------------------------------------------------
# New-build pipeline: geocode + loan filter + score + dedupe + rank
# ---------------------------------------------------------------------------

def geocode_and_score_newbuild(listings: list[dict], cache: dict, geo_cache: dict, loan_ratio_max: float) -> list[dict]:
    scored: list[dict] = []
    fresh = 0
    print(f"\n  Geocoding {len(listings)} new build listings …")
    for listing in listings:
        ok, was_fresh = _geocode_pks_listing(listing, cache, geo_cache)
        if was_fresh:
            fresh += 1
        if not ok:
            continue
        loan = listing.get("housing_company_loan_eur")
        if loan is not None:
            dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
            if dfp > 0 and float(loan) / dfp > loan_ratio_max:
                continue
        listing["_search_pass"] = "new_build"
        listing["monthly_cost_eur"] = round(monthly_cost_eur(listing), 2)
        listing["score"] = score_uusimaa_listing(listing)
        scored.append(listing)
    print(f"  {fresh} fresh geocodes")
    return scored


def dedupe_and_rank_newbuild(scored: list[dict], top_n: int = NEWBUILD_TOP_N) -> list[dict]:
    """Keep only the highest-scoring listing per street (same street = same
    development project), then cap at top_n for a focused shortlist."""
    scored.sort(key=lambda l: -l["score"])
    seen_bldg: set[str] = set()
    deduped: list[dict] = []
    for l in scored:
        addr = l.get("address", "")
        street = re.sub(r"\s+\d+.*$", "", addr.split(",")[0]).strip()
        key = f"{street}|{l.get('city', '')}".lower()
        if key not in seen_bldg:
            seen_bldg.add(key)
            deduped.append(l)
    top = deduped[:top_n]
    for rank, l in enumerate(top, 1):
        l["rank"] = rank
    print(f"  New build passing: {len(deduped)} unique buildings → top {len(top)}")
    return top


# ---------------------------------------------------------------------------
# Risk flags shown on report cards
# ---------------------------------------------------------------------------

def _loan_ratio_flag(l: dict) -> list[tuple[str, str, str]]:
    """Shared: warn when the housing-company loan share is high (identical in both modes)."""
    dfp = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
    loan = l.get("housing_company_loan_eur")
    if loan is not None and dfp > 0:
        ratio = float(loan) / dfp
        if ratio > 0.35:
            return [(f"Yhtiölainaosuus {ratio*100:.0f}% — rahoitusvastike may spike when interest-only ends",
                      "https://www.taloustaito.fi/koti/isannointiliitto-laski-nain-rajusti-uudiskohteen-rahoitusvastike-voi-nousta/", "taloustaito")]
    return []


def listing_red_flags(l: dict) -> list[tuple[str, str, str]]:
    """Per-listing risk warnings for tram-corridor listings: (text, source_url, source_label)."""
    flags = []
    stop = l.get("nearest_stop") or ""

    if stop == "Rajakylä":
        flags.append(("No tram stop on final route — tram re-routed via Fazerila",
                       "https://fi.wikipedia.org/wiki/Vantaan_pikaraitiotie", "wikipedia"))
    if stop == "Aviapolis":
        flags.append(("Airport extension terminus unresolved until 2027",
                       "https://yle.fi/a/74-20194836", "yle.fi"))
    if stop in ("Hakunila", "Hevoshaanpolku"):
        flags.append(("SATO operates ~6,000 units here — may suppress private achievable rents",
                       "https://www.sato.fi/en/kotona/neighborhood/good-bad-and-ugly-residential-areas/54696532", "sato.fi"))
    if stop == "Länsimäki":
        flags.append(("Prices 35% below Vantaa avg; 50% of planned units conditional on 110kV burial",
                       "https://www.vantaa.fi/fi/kaavoitus/kaavat/lansimaen-kaavarunko-ohjaa-keskustan-kasvua-ja-laajenemista", "kaavarunko"))

    flags += _loan_ratio_flag(l)

    hoito = l.get("hoitovastike_eur_month") or 0
    sqm = float(l.get("size_sqm") or 0)
    if hoito and sqm > 0 and hoito / sqm > 6.5:
        flags.append((f"Hoitovastike {hoito/sqm:.1f} €/m²/mo vs 4.74 € Vantaa avg — investigate cause",
                       "https://www.kiinteistoliitto.fi/uutiset/nayta/?id=16859&title=hoitovastikekysely2025", "kiinteistöliitto"))

    return flags


def listing_red_flags_uusimaa(l: dict) -> list[tuple[str, str, str]]:
    """Generic risk warnings for Uusimaa listings (no tram-stop-specific checks)."""
    flags = list(_loan_ratio_flag(l))

    hoito = l.get("hoitovastike_eur_month") or 0
    sqm = float(l.get("size_sqm") or 0)
    if hoito and sqm > 0 and hoito / sqm > 6.5:
        flags.append((f"Hoitovastike {hoito/sqm:.1f} €/m²/mo — high vs ~4–5 € avg in PKS",
                       "https://www.kiinteistoliitto.fi/uutiset/nayta/?id=16859&title=hoitovastikekysely2025", "kiinteistöliitto"))

    year = l.get("year_built") or 0
    pipe_done = _eval_pipe_done(l.get("pipe_renovation_info"), l.get("pipe_renovation_year"))
    if 1975 <= year <= 1995 and not pipe_done:
        flags.append(("Pipe renovation liability — 1975–1995 build without confirmed renovation",
                       "https://www.kiinteistoliitto.fi/", "kiinteistöliitto"))

    return flags
