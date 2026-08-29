#!/usr/bin/env python3.10
"""
Oikotie scraper — Playwright/WebKit, no context.dev.

Searches all 15 Vantaan ratikka corridor districts in one query,
paginates through every result page, then verifies loan & pipe
renovation on individual listing pages with a disk cache.

Criteria:
  - Kerrostalo only (buildingType=1)
  - 1–2 rooms
  - Velaton hinta ≤ 200 000 €
  - Housing company loan ≤ 50 % of debt-free price
  - Built ≥ 2000  OR  older with confirmed pipe renovation

Outputs: results.json, results.csv, report.html
Cache:   listing_cache.json  (individual page checks, survives re-runs)

Usage:
    python3.10 scraper.py
"""

import csv, json, math, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

_DATA = Path(os.environ.get("DATA_DIR", "."))
_DATA.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Tramline district location IDs (oikotie cardId / cardType 4 = neighbourhood)
# Discovered via oikotie autocomplete API (/api/3.0/location?query=…)
# ---------------------------------------------------------------------------
TRAMLINE_LOCATIONS: list[list] = [
    [1786,      4, "Hakunila, Vantaa"],
    [1785,      4, "Vaarala, Vantaa"],
    [1757,      4, "Hiekkaharju, Vantaa"],
    [1758,      4, "Tikkurila, Vantaa"],
    [1759,      4, "Jokiniemi, Vantaa"],
    [1765,      4, "Koivuhaka, Vantaa"],
    [1754,      4, "Pakkala, Vantaa"],
    [14927926,  4, "Aviapolis, Vantaa"],
    [1787,      4, "Rajakylä, Vantaa"],
    [1783,      4, "Länsimäki, Vantaa"],
    [16835029,  4, "Kaskela, Vantaa"],
    [335120,    4, "Mellunmäki, Helsinki"],
]

PRICE_MAX       = 200_000
LOAN_RATIO_MAX  = 0.50      # loan / debt_free_price
MAX_STOP_DIST_M = 500       # max walking distance to any tram stop

# Monthly cost model
DOWN_PAYMENT_EUR  = 30_000
LOAN_MARGIN       = 0.006   # 0.6 % bank margin
EURIBOR_12M       = 0.02993 # 12-month Euribor 2026-07-24; update if stale
LOAN_YEARS        = 25

TRAM_STOPS: list[tuple[str, float, float]] = [
    # (name, lon, lat) — from Vantaa city GIS FeatureServer
    ("Aviapolis",                   24.956, 60.303),
    ("Ilmailumuseo",                24.958, 60.306),
    ("Backasbrinken/Pakkalanrinne", 24.952, 60.292),
    ("Muura",                       24.951, 60.298),
    ("Annefred",                    24.973, 60.296),
    ("Annefredinsilta",             24.985, 60.294),
    ("Viertola",                    25.019, 60.291),
    ("Silkkitehdas",                25.033, 60.289),
    ("Tikkuraitti",                 25.037, 60.293),
    ("Tikkurilan asema",            25.045, 60.294),
    ("Jokiniemi",                   25.053, 60.290),
    ("Koivuhaka",                   25.006, 60.292),
    ("Pakkala",                     24.960, 60.290),
    ("Jumbo",                       24.967, 60.290),
    ("Kuusikko",                    25.069, 60.285),
    ("Porttipuisto",                25.087, 60.282),
    ("Kaskela",                     25.098, 60.281),
    ("Hakunila",                    25.106, 60.278),
    ("Hevoshaanpolku",              25.104, 60.274),
    ("Vaarala",                     25.100, 60.267),
    ("Kuussilta",                   25.093, 60.262),
    ("Fazerila",                    25.105, 60.258),
    ("Rajakylä",                    25.112, 60.251),
    ("Länsimäki",                   25.111, 60.244),
    ("Mellunmäki",                  25.109, 60.239),
    ("Backas",                      24.960, 60.290),
]

# ---------------------------------------------------------------------------
# PKS (Helsinki / Espoo / Vantaa) search constants
# ---------------------------------------------------------------------------
UUSIMAA_LOCATIONS: list[list] = [
    [64, 6, "Helsinki"],
    [39, 6, "Espoo"],
    [65, 6, "Vantaa"],
]

UUSIMAA_PRICE_MAX      = 200_000
UUSIMAA_LOAN_RATIO_MAX = 0.50
UUSIMAA_TOP_UNRENTED   = 5    # max non-rented listings shown in Uusimaa watch list
NEWBUILD_TOP_N         = 50   # top N after per-building dedup; use --force to refresh

# Major train/metro stations — (name, lat, lon)
TRANSPORT_HUBS: list[tuple[str, float, float]] = [
    ("Helsinki Central",  60.1698, 24.9382),
    ("Pasila",            60.1925, 24.9335),
    ("Tikkurila",         60.2897, 25.0403),
    ("Leppävaara",        60.2194, 24.8150),
    ("Kerava",            60.4033, 25.1056),
    ("Kamppi metro",      60.1694, 24.9328),
    ("Itäkeskus metro",   60.2111, 25.0815),
    ("Matinkylä metro",   60.1621, 24.7373),
    ("Ruoholahti metro",  60.1639, 24.9151),
]

# Major malls — (name, lat, lon)
MAJOR_MALLS: list[tuple[str, float, float]] = [
    ("Kamppi",    60.1696, 24.9334),
    ("Tripla",    60.1981, 24.9300),
    ("Sello",     60.2181, 24.8108),
    ("Jumbo",     60.2911, 24.9646),
    ("Iso Omena", 60.1621, 24.7373),
    ("Itis",      60.2111, 25.0815),
    ("REDI",      60.1869, 24.9792),
]

HELSINKI_CENTRAL_COORDS: tuple[float, float] = (60.1698, 24.9382)

MAX_DETAIL_CHECKS = 9999    # effectively unlimited

BASE_URL    = "https://asunnot.oikotie.fi"
_CACHE_FILE          = _DATA / "listing_cache.json"
_GEO_CACHE_FILE      = _DATA / "geocode_cache.json"
_RESULTS_CACHE_FILE  = _DATA / "results_cache.json"
RESULTS_CACHE_TTL_HOURS = 12  # use --force to bypass after changing filter constants


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_search_url(page_num: int = 1) -> str:
    import urllib.parse
    loc = urllib.parse.quote(json.dumps(TRAMLINE_LOCATIONS))
    return (
        f"{BASE_URL}/myytavat-asunnot"
        f"?pagination={page_num}"
        f"&cardType=100"
        f"&locations={loc}"
        f"&habitationType[]=1"         # free-market only (excludes asumisoikeus)
        f"&price[max]={PRICE_MAX}"
    )


def build_uusimaa_search_url(page_num: int = 1) -> str:
    import urllib.parse
    loc = urllib.parse.quote(json.dumps(UUSIMAA_LOCATIONS))
    return (
        f"{BASE_URL}/myytavat-asunnot"
        f"?pagination={page_num}"
        f"&cardType=100"
        f"&locations={loc}"
        f"&habitationType[]=1"
        f"&price[max]={UUSIMAA_PRICE_MAX}"
        f"&roomCount[]=1&roomCount[]=2"
        f"&buildingType[]=1&buildingType[]=256"
        f"&secondarySearchType=1"
    )


def build_newbuild_search_url(page_num: int = 1) -> str:
    import urllib.parse
    loc = urllib.parse.quote(json.dumps(UUSIMAA_LOCATIONS))
    return (
        f"{BASE_URL}/myytavat-asunnot"
        f"?pagination={page_num}"
        f"&cardType=100"
        f"&secondarySearchType=1"
        f"&newDevelopment=1"
        f"&locations={loc}"
        f"&habitationType[]=1"
        f"&price[max]={UUSIMAA_PRICE_MAX}"
        f"&roomCount[]=1&roomCount[]=2"
    )


# ---------------------------------------------------------------------------
# Pipe renovation patterns
# ---------------------------------------------------------------------------

_RENO_TERM = re.compile(
    r"(putkiremontti|linjasaneeraus|putkisto\s*uusittu|putkisto\s*saneerattu"
    r"|putkisaneeraus|linjasaneerattu|putkikorjaus)",
    re.IGNORECASE,
)
_DONE_TERM = re.compile(
    r"(tehty|valmis|valmistunut|suoritettu|uusittu|saneerattu|remontoitu"
    r"|päivitetty|toteutettu|korjattu)",
    re.IGNORECASE,
)
_IN_PROGRESS_TERM = re.compile(
    r"(parhaillaan\s+käynnissä|käynnissä|menossa|valmistuttua|suunnitteilla"
    r"|tulossa|aloitetaan)",
    re.IGNORECASE,
)
_RENTED_TERM = re.compile(
    r"(vuokralainen|asunto\s+on\s+vuokrattu|on\s+vuokrattu"
    r"|myydään\s+vuokrattuna|vuokrattuna\s+myytävä"
    r"|kuukausivuokra|nykyinen\s+vuokralainen|vuokrasopimus\s+on"
    r"|vuokra\s+on\s+[\d\s]+\s*€|vuokra\s+[\d\s]+\s*€\s*/\s*kk"
    r"|vuokratuottoa\s+heti|nauti\s+hyvää\s+vuokratuottoa)",
    re.IGNORECASE,
)


def _eval_pipe_done(snippet: Optional[str], year: Optional[int]) -> bool:
    """Evaluate pipe renovation completion from snippet + year.

    In-progress language vetoes done-terms; future year overrides done-terms.
    """
    if not snippet:
        return False
    if _IN_PROGRESS_TERM.search(snippet):
        return False
    done = bool(_DONE_TERM.search(snippet))
    if not done and year and year <= datetime.now().year:
        done = True
    if done and year and year >= datetime.now().year:
        done = False
    return done


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    try:
        return json.load(open(_CACHE_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    with open(_CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2)


def _load_geo_cache() -> dict:
    try:
        return json.load(open(_GEO_CACHE_FILE, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_geo_cache(cache: dict) -> None:
    with open(_GEO_CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=2)


def _load_results_cache() -> dict | None:
    try:
        data = json.load(open(_RESULTS_CACHE_FILE, encoding="utf-8"))
        age_h = (datetime.now() - datetime.fromisoformat(data["timestamp"])).total_seconds() / 3600
        if age_h <= RESULTS_CACHE_TTL_HOURS:
            return data
        print(f"Results cache expired ({age_h:.1f}h old, TTL={RESULTS_CACHE_TTL_HOURS}h) — running full pipeline.")
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def _save_results_cache(confirmed: list, candidates: list, tram_rented_out: list,
                        uusimaa_rented: list, uusimaa_top5: list,
                        uusimaa_passing: list, newbuild_pks: list) -> None:
    data = {
        "timestamp":       datetime.now().isoformat(),
        "confirmed":       confirmed,
        "candidates":      candidates,
        "tram_rented_out": tram_rented_out,
        "uusimaa_rented":  uusimaa_rented,
        "uusimaa_top5":    uusimaa_top5,
        "uusimaa_passing": uusimaa_passing,
        "newbuild_pks":    newbuild_pks,
    }
    with open(_RESULTS_CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print(f"Saved → {_RESULTS_CACHE_FILE}  (valid for {RESULTS_CACHE_TTL_HOURS}h)")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_tram_stop(lat: float, lon: float) -> tuple[str, float]:
    best_name, best_dist = "", float("inf")
    for name, slon, slat in TRAM_STOPS:
        d = haversine_m(lat, lon, slat, slon)
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name, best_dist


def nearest_hub(lat: float, lon: float) -> tuple[str, float]:
    best_name, best_dist = "", float("inf")
    for name, hlat, hlon in TRANSPORT_HUBS:
        d = haversine_m(lat, lon, hlat, hlon)
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name, best_dist


def nearest_mall(lat: float, lon: float) -> tuple[str, float]:
    best_name, best_dist = "", float("inf")
    for name, mlat, mlon in MAJOR_MALLS:
        d = haversine_m(lat, lon, mlat, mlon)
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name, best_dist


def geocode_address(address: str, city: str, geo_cache: dict) -> Optional[tuple[float, float]]:
    key = f"{address}, {city}, Finland"
    if key in geo_cache:
        return geo_cache[key]
    # Strip apartment identifier (e.g. "A 12", "B 3") to improve Nominatim match rate.
    street = re.sub(r"\s+[A-Za-z]\s+\d+$", "", address.split(",")[0]).strip()
    params = urllib.parse.urlencode({
        "street": street, "city": city, "countrycodes": "fi",
        "format": "json", "limit": 1,
    })
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "oikotie-ratikka-scraper/1.0 tung@tekai.fi"}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            if data:
                result: tuple[float, float] = (float(data[0]["lat"]), float(data[0]["lon"]))
                geo_cache[key] = result
                return result
            break  # empty result — address not found, don't retry
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 15 * (2 ** attempt)  # 15s, 30s, 60s, 120s
                print(f"    geocode 429 — waiting {wait}s before retry …", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"    geocode warning: {address}: {exc}", file=sys.stderr)
                break
        except Exception as exc:
            print(f"    geocode warning: {address}: {exc}", file=sys.stderr)
            break
    geo_cache[key] = None
    return None


# Tram transformation score per stop (0–5 pts).
# 0 = already a major transit hub — tram adds negligible marginal value, prices priced-in.
# 2 = within an existing hub's catchment — already benefiting from existing transit.
# 5 = bus-only today; tram will meaningfully transform the neighbourhood.
# Sources: Vantaa city kaavarunko plans, WSP research, Sp-Koti Feb 2025, YLE reporting.
_STOP_TRANSFORMATION: dict[str, int] = {
    # --- Existing major hubs (0 pts) ---
    "Tikkurilan asema":            0,  # commuter rail + Allegro + airport express; +22% price surge already
    "Mellunmäki":                  0,  # metro terminus; Helsinki planning 800 new residents on-site anyway

    # --- Within existing hub catchment (2 pts) ---
    "Tikkuraitti":                 2,  # 200 m from Tikkurila station, same price zone
    "Silkkitehdas":                2,  # Tikkurila residential district, already elevated prices
    "Jokiniemi":                   2,  # immediately east of Tikkurila station
    "Koivuhaka":                   2,  # immediately west of Tikkurila station
    "Hiekkaharju":                 2,  # served by Kerava commuter line trains
    "Aviapolis":                   1,  # near Ring Rail, BUT airport tram extension unresolved (decision 2027)
    "Ilmailumuseo":                2,  # between airport and Pakkala; limited residential market

    # --- Bus-only today; tram is transformative (5 pts) ---
    # Western arc
    "Backasbrinken/Pakkalanrinne": 5,
    "Backas":                      5,
    "Pakkala":                     5,
    "Muura":                       5,
    "Jumbo":                       5,  # major retail hub but no rail; tram adds mass-transit access
    "Annefred":                    5,
    "Annefredinsilta":             5,
    "Viertola":                    5,

    # Eastern arc — research confirms these as top investment corridors
    "Kuusikko":                    5,
    "Porttipuisto":                5,
    "Kaskela":                     5,  # YIT Kaskelanrinne actively building 100 m from stop
    "Hakunila":                    5,  # BEST: city plan +6000 residents, 48% sales volume rise in 2024
    "Hevoshaanpolku":              5,  # Hakunila cluster
    "Fazerila":                    5,  # NEW district: urban design won Apr 2025, Fazer brand anchor
    "Vaarala":                     5,  # tram depot site (€71.7M) — permanent infrastructure anchor
    "Kuussilta":                   5,
    "Rajakylä":                    5,  # note: tram re-routed via Fazerila, stop still exists at boundary
    "Länsimäki":                   5,  # 2700 apts planned; ⚠ 1/3 conditional on 110kV line burial
}

# Brief investment note shown on HTML card for notable stops.
_STOP_NOTE: dict[str, str] = {
    "Tikkurilan asema": "Premium hub — tram already priced in (+22% recent surge)",
    "Mellunmäki":       "Metro terminus — Helsinki planning 800 new residents + mixed-use",
    "Aviapolis":        "⚠ Airport tram extension unresolved — terminus decision expected 2027",
    "Kaskela":          "YIT Kaskelanrinne actively building near the stop",
    "Hakunila":         "📈 #1 investment area — city plan: +6 000 residents, new shopping centre; sales +48% YoY",
    "Hevoshaanpolku":   "📈 Hakunila cluster — same strong growth fundamentals (+48% sales YoY)",
    "Fazerila":         "🏗 New district — Fazer brand anchor, design competition won Sep 2025, asemakaava next",
    "Vaarala":          "🏗 Tram depot site (€71.7 M) — permanent infrastructure anchor",
    "Länsimäki":        "📈 High upside — 2 700 apts planned ⚠ half conditional on 110 kV power line burial",
    "Rajakylä":         "⚠ Tram re-routed via Fazerila — Rajakylä has no tram stop on the final route",
}

# Source links for each stop note: list of (url, short_label) pairs
_STOP_LINKS: dict[str, list[tuple[str, str]]] = {
    "Tikkurilan asema": [
        ("https://www.asunnollehinta.fi/kerrostalojen_hintataulukko_vantaa", "hintataulukko"),
        ("https://spkoti.fi/2025/02/06/ratikka-tulee-nostamaan-asuntojen-hintoja-vantaalla-jo-rakentamisvaiheessa/", "sp-koti"),
    ],
    "Mellunmäki": [
        ("https://www.hel.fi/en/news/new-centre-and-800-new-residents-in-mellunmaki", "hel.fi"),
        ("https://www.rakennuslehti.fi/2025/03/mellunmaki-aiotaan-myllata-uuteen-uskoon-keskusta-kuntoon-ja-800-uutta-asukasta/", "rakennuslehti"),
    ],
    "Aviapolis": [
        ("https://yle.fi/a/74-20194836", "yle.fi"),
        ("https://www.vantaa.fi/en/topical/release/vantaa-light-rails-final-stop-options-be-planned-helsinki-airports-core-area-co-operation-finavia", "vantaa.fi"),
    ],
    "Kaskela": [
        ("https://www.yit.fi/en/homes/apartments-for-sale/vantaa/kaskelanrinne", "YIT Kaskelanrinne"),
        ("https://fi.wikipedia.org/wiki/Vantaan_pikaraitiotie", "wikipedia"),
    ],
    "Hakunila": [
        ("https://www.vantaa.fi/fi/kaavoitus/kaavat/hakunilan-keskustan-kaavarunko", "kaavarunko"),
        ("https://huoneistokeskus.fi/ajankohtaista/markkinakatsaukset/asuntomarkkinakatsaus-kysynnassa-elpymisen-merkkeja-raiteiden-varsilla/", "+48% myynti"),
    ],
    "Hevoshaanpolku": [
        ("https://www.vantaa.fi/fi/kaavoitus/kaavat/hakunilan-keskustan-kaavarunko", "kaavarunko"),
        ("https://huoneistokeskus.fi/ajankohtaista/markkinakatsaukset/asuntomarkkinakatsaus-kysynnassa-elpymisen-merkkeja-raiteiden-varsilla/", "+48% myynti"),
    ],
    "Fazerila": [
        ("https://www.vantaa.fi/fi/ajankohtaista/tiedote/kaupunkiymparistolautakunnassa-fazerila-santamalmin-alueen-suunnittelukilpailu", "tiedote"),
        ("https://www.vantaa.fi/fi/hankkeet/hanke/fazerila-santamalmin-suunnittelukilpailu", "hanke"),
    ],
    "Vaarala": [
        ("https://yle.fi/a/74-20211498", "yle.fi"),
        ("https://fi.wikipedia.org/wiki/Vantaan_pikaraitiotie", "wikipedia"),
    ],
    "Länsimäki": [
        ("https://www.vantaa.fi/fi/kaavoitus/kaavat/lansimaen-kaavarunko-ohjaa-keskustan-kasvua-ja-laajenemista", "kaavarunko"),
    ],
    "Rajakylä": [
        ("https://fi.wikipedia.org/wiki/Vantaan_pikaraitiotie", "wikipedia"),
        ("https://www.vantaa.fi/fi/hankkeet/hanke/raitiotien-rakentaminen-hakunilasta-fazerilaan", "vantaa.fi"),
    ],
}


def score_listing(listing: dict) -> int:
    """Score 0–125. Higher = better investment candidate."""
    score = 0

    # Building quality (0–40 pts)
    year      = listing.get("year_built") or 0
    pipe_done = _eval_pipe_done(
        listing.get("pipe_renovation_info"), listing.get("pipe_renovation_year")
    )
    reno_year = listing.get("pipe_renovation_year") or 0

    if year >= 2015:
        score += 40
    elif year >= 2010:
        score += 35
    elif year >= 2000:
        score += 28
    elif pipe_done and reno_year >= 2015:
        score += 25
    elif pipe_done and reno_year >= 2005:
        score += 20
    elif pipe_done:
        score += 15
    else:
        score += 5   # candidate — pipe reno unverified

    # Distance to nearest tram stop (0–20 pts)
    # Two brackets: walkable (<200 m) vs further but still within 500 m
    dist = listing.get("distance_m") or 999
    if dist < 200:
        score += 20
    elif dist <= 500:
        score += 10

    # Tram transformation potential (0–5 pts)
    # Distinguishes existing major hubs (0) from stops that will be genuinely uplifted (5).
    stop = listing.get("nearest_stop") or ""
    score += _STOP_TRANSFORMATION.get(stop, 5)

    # Price per sqm (0–20 pts) — lower is better
    dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
    sqm = float(listing.get("size_sqm") or 0)
    if dfp > 0 and sqm > 0:
        ppsqm = dfp / sqm
        if ppsqm < 1500:    score += 20
        elif ppsqm < 2000:  score += 17
        elif ppsqm < 2500:  score += 13
        elif ppsqm < 3000:  score += 9
        elif ppsqm < 3500:  score += 5
        elif ppsqm < 4500:  score += 2

    # Loan ratio (0–10 pts) — lower is better
    # When velaton hinta == selling price the company loan is 0 (not separately listed).
    loan = listing.get("housing_company_loan_eur")
    price = listing.get("price_eur")
    if loan is None and dfp and price and abs(dfp - float(price)) < 1:
        loan = 0.0
    if loan is None:
        score += 5
    else:
        loan = float(loan)
        if loan == 0:
            score += 10
        elif dfp > 0:
            ratio = loan / dfp
            if ratio <= 0.05:    score += 9
            elif ratio <= 0.15:  score += 7
            elif ratio <= 0.25:  score += 5
            elif ratio <= 0.35:  score += 3
            else:                score += 1

    # Non-mortgage monthly costs — hoitovastike + tonttivuokra only (0–30 pts)
    # Mortgage builds equity; these fees are pure sunk cost. Lower = better.
    # 0 or missing treated as unknown → 0 pts (conservative, avoids rewarding missing data).
    non_mort = (listing.get("hoitovastike_eur_month") or 0) + (listing.get("tonttivuokra_eur_month") or 0)
    if non_mort > 0:
        if non_mort <= 100:   score += 30
        elif non_mort <= 150: score += 25
        elif non_mort <= 200: score += 18
        elif non_mort <= 250: score += 12
        elif non_mort <= 300: score += 6

    return score


def score_uusimaa_listing(listing: dict) -> int:
    """Score 0–100 for Uusimaa non-tram listings. Higher = better investment candidate.

    Factors: transport hub proximity (25), Helsinki Central distance (15),
    nearest mall (10), building quality (30), price/m² (10), loan ratio (5),
    monthly non-mortgage costs (5).
    """
    score = 0

    lat = listing.get("lat")
    lon = listing.get("lon")

    # Transport hub proximity (0–25 pts) — rail/metro drives tenant demand
    hub_dist = listing.get("hub_distance_m")
    if hub_dist is None and lat is not None:
        _, hub_dist = nearest_hub(lat, lon)
    if hub_dist is not None:
        if hub_dist < 300:    score += 25
        elif hub_dist < 600:  score += 20
        elif hub_dist < 1000: score += 15
        elif hub_dist < 1500: score += 10
        elif hub_dist < 2500: score += 5

    # Helsinki Central proximity (0–15 pts) — distance-to-center is the #1 price driver
    hc_km = listing.get("helsinki_central_km")
    if hc_km is None and lat is not None:
        hc_km = haversine_m(lat, lon, HELSINKI_CENTRAL_COORDS[0], HELSINKI_CENTRAL_COORDS[1]) / 1000
    if hc_km is not None:
        if hc_km < 2:    score += 15
        elif hc_km < 4:  score += 12
        elif hc_km < 7:  score += 8
        elif hc_km < 12: score += 4

    # Nearest major mall (0–10 pts) — services & walkability signal
    mall_dist = listing.get("mall_distance_m")
    if mall_dist is None and lat is not None:
        _, mall_dist = nearest_mall(lat, lon)
    if mall_dist is not None:
        if mall_dist < 500:    score += 10
        elif mall_dist < 1000: score += 8
        elif mall_dist < 1500: score += 5
        elif mall_dist < 2500: score += 2

    # Building quality (0–30 pts)
    year      = listing.get("year_built") or 0
    pipe_done = _eval_pipe_done(
        listing.get("pipe_renovation_info"), listing.get("pipe_renovation_year")
    )
    reno_year = listing.get("pipe_renovation_year") or 0
    if year >= 2015:       score += 30
    elif year >= 2010:     score += 25
    elif year >= 2000:     score += 20
    elif pipe_done and reno_year >= 2015: score += 20
    elif pipe_done and reno_year >= 2005: score += 15
    elif pipe_done:        score += 12
    else:                  score += 3

    # Price per m² (0–10 pts) — Helsinki prices are higher; scale adjusted
    dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
    sqm = float(listing.get("size_sqm") or 0)
    if dfp > 0 and sqm > 0:
        ppsqm = dfp / sqm
        if ppsqm < 2000:    score += 10
        elif ppsqm < 3000:  score += 7
        elif ppsqm < 4000:  score += 4
        elif ppsqm < 5000:  score += 1

    # Loan ratio (0–5 pts)
    loan = listing.get("housing_company_loan_eur")
    if loan is None and dfp and listing.get("price_eur"):
        if abs(dfp - float(listing.get("price_eur") or 0)) < 1:
            loan = 0.0
    if loan is None:
        score += 2
    else:
        loan = float(loan)
        if loan == 0:
            score += 5
        elif dfp > 0:
            ratio = loan / dfp
            if ratio <= 0.15:   score += 4
            elif ratio <= 0.30: score += 3
            elif ratio <= 0.50: score += 1

    # Monthly non-mortgage costs (0–5 pts)
    non_mort = (listing.get("hoitovastike_eur_month") or 0) + (listing.get("tonttivuokra_eur_month") or 0)
    if non_mort > 0:
        if non_mort <= 150:   score += 5
        elif non_mort <= 200: score += 4
        elif non_mort <= 250: score += 3
        elif non_mort <= 300: score += 1

    return score


def monthly_mortgage(loan_eur: float) -> float:
    """Annuity payment for given loan at EURIBOR_12M + LOAN_MARGIN over LOAN_YEARS."""
    if loan_eur <= 0:
        return 0.0
    r = (EURIBOR_12M + LOAN_MARGIN) / 12
    n = LOAN_YEARS * 12
    return loan_eur * r * (1 + r) ** n / ((1 + r) ** n - 1)


def monthly_cost_eur(listing: dict) -> float:
    """Total monthly out-of-pocket: mortgage + hoitovastike + tonttivuokra."""
    dfp  = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
    loan = max(0.0, dfp - DOWN_PAYMENT_EUR)
    mort = monthly_mortgage(loan)
    hoito = float(listing.get("hoitovastike_eur_month") or 0)
    tontti = float(listing.get("tonttivuokra_eur_month") or 0)
    return mort + hoito + tontti


# ---------------------------------------------------------------------------
# Number parsing helper
# ---------------------------------------------------------------------------

def _parse_fin_num(s: str) -> Optional[float]:
    """Parse Finnish number string like '82 000' or '223,68' to float."""
    s = s.strip().replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Search results page parser
# ---------------------------------------------------------------------------

def parse_card_text(text: str, url: str) -> Optional[dict]:
    """Turn raw card innerText into a listing dict."""
    result: dict = {"listing_url": url}

    # Price: first "NNN €" pattern
    m = re.search(r"([\d][\d\s\xa0]*)\s*€", text)
    if m:
        v = _parse_fin_num(m.group(1))
        if v:
            result["price_eur"] = v

    # Size: "64 m²" or "43,5 m²"
    m = re.search(r"([\d]+(?:[,.]\d+)?)\s*m²", text)
    if m:
        v = _parse_fin_num(m.group(1))
        if v:
            result["size_sqm"] = v

    # Rooms
    m = re.search(r"Huoneita\s+(\d+)", text)
    if m:
        result["room_count"] = int(m.group(1))

    # Floor: looks for N/M after "Kerros" line
    m = re.search(r"Kerros\s*\n\s*(\d+/\d+)", text)
    if not m:
        m = re.search(r"\b(\d{1,2}/\d{1,2})\b", text)
    if m:
        result["floor"] = m.group(1)

    # Building type + year: "Kerrostalo, 1978"
    m = re.search(
        r"(Kerrostalo|Rivitalo|Omakotitalo|Paritalo|Luhtitalo|Erillistalo|Puutalo)[,\s]+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        result["property_type"] = m.group(1).lower()
        result["year_built"] = int(m.group(2))

    # Address: first line containing a comma that isn't a price/size line
    for line in text.split("\n"):
        line = line.strip()
        if (
            "," in line
            and "€" not in line
            and "m²" not in line
            and "Kerros" not in line
            and "Huoneita" not in line
            and not re.fullmatch(r"\d+/\d+", line)
        ):
            result["address"] = line
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                result["district"] = parts[-2]
                result["city"] = parts[-1].lower()
            elif len(parts) == 2:
                result["district"] = parts[-1]
            break

    return result if len(result) > 3 else None


_TRAM_LINK_SELECTOR    = 'a[href*="/myytavat-asunnot/vantaa/"], a[href*="/myytavat-asunnot/helsinki/"]'
_UUSIMAA_LINK_SELECTOR = 'a[href*="/myytavat-asunnot/"]'
_NEWBUILD_LINK_SELECTOR = 'a[href*="/myytavat-asunnot/"], a[href*="/myytavat-uudisasunnot/"]'


def scrape_search_page(page, page_num: int,
                       url_builder=None,
                       link_selector: str = None) -> tuple[list[dict], int, int]:
    """Load one results page; return (listings, total_count, total_pages)."""
    url_builder   = url_builder   or build_search_url
    link_selector = link_selector or _TRAM_LINK_SELECTOR
    url = url_builder(page_num)
    page.goto(url, wait_until="networkidle", timeout=45000)
    body = page.inner_text("body")

    m = re.search(r"(\d+)\s*Kohdetta.*?Sivu\s*(\d+)/(\d+)", body, re.DOTALL)
    total       = int(m.group(1)) if m else 0
    total_pages = int(m.group(3)) if m else 1

    links = page.query_selector_all(link_selector)
    listings: list[dict] = []
    seen: set[str] = set()
    for link in links:
        href = link.get_attribute("href") or ""
        if not href or href in seen:
            continue
        # For the broad Uusimaa selector, skip non-listing hrefs (no numeric ID segment)
        if not re.search(r"/myytavat-asunnot/\w[\w-]*/\d+", href):
            continue
        seen.add(href)
        full_url = (BASE_URL + href) if not href.startswith("http") else href
        card_text = page.evaluate(
            "(el) => el.parentElement?.parentElement?.innerText ?? ''", link
        )
        listing = parse_card_text(card_text or "", full_url)
        if listing:
            listings.append(listing)

    return listings, total, total_pages


# ---------------------------------------------------------------------------
# Individual listing page parser
# ---------------------------------------------------------------------------

def fetch_listing_details(page, url: str, cache: dict) -> dict:
    """Load individual listing page; return loan + pipe reno + rental details."""
    if url in cache and "hoitovastike_eur_month" in cache[url]:
        return cache[url]

    try:
        page.goto(url, wait_until="networkidle", timeout=40000)
        text = page.inner_text("body")
    except Exception as exc:
        print(f"    warning: {url}: {exc}", file=sys.stderr)
        result = {"pipe_renovation_done": False, "pipe_renovation_info": None,
                  "pipe_renovation_year": None, "housing_company_loan_eur": None,
                  "debt_free_price_eur": None, "is_rented_out": False,
                  "rented_out_info": None, "hoitovastike_eur_month": None,
                  "tonttivuokra_eur_month": None}
        cache[url] = result
        return result

    result: dict = {}

    # Velaton hinta
    m = re.search(r"Velaton hinta\s*\n+\s*([\d\s\xa0]+(?:[,.]\d+)?)\s*€", text)
    if m:
        result["debt_free_price_eur"] = _parse_fin_num(m.group(1))

    # Myyntihinta (authoritative sale price)
    m = re.search(r"Myyntihinta\s*\n+\s*([\d\s\xa0]+(?:[,.]\d+)?)\s*€", text)
    if m:
        result["price_eur"] = _parse_fin_num(m.group(1))

    # Velkaosuus / yhtiölainaa (remaining housing company loan)
    m = re.search(r"(?:Velkaosuus|Yhtiölainaa|Lainaosuus)\s*\n+\s*([\d\s\xa0]+(?:[,.]\d+)?)\s*€", text)
    if m:
        result["housing_company_loan_eur"] = _parse_fin_num(m.group(1))
    elif re.search(r"Lainaosuuden maksu\s*\n+\s*Ei\b", text, re.IGNORECASE):
        result["housing_company_loan_eur"] = 0.0
    else:
        result["housing_company_loan_eur"] = None   # unknown

    # Pipe renovation
    pipe_m = _RENO_TERM.search(text)
    if pipe_m:
        s = max(0, pipe_m.start() - 150)
        e = min(len(text), pipe_m.end() + 150)
        snippet = text[s:e].strip()
        done = bool(_DONE_TERM.search(snippet))
        year_m = re.search(r"\b(19[89]\d|20[012]\d)\b", snippet)
        if not done and year_m:
            if int(year_m.group()) <= datetime.now().year:
                done = True
        result.update({
            "pipe_renovation_done": done,
            "pipe_renovation_info": snippet,
            "pipe_renovation_year": int(year_m.group()) if year_m else None,
        })
    else:
        result.update({"pipe_renovation_done": False,
                       "pipe_renovation_info": None, "pipe_renovation_year": None})

    # Hoitovastike (monthly maintenance fee) — page format: "393,75\xa0€ / kk"
    m = re.search(r"Hoitovastike\s*\n+([\d\xa0\s]+(?:[,.]\d+)?)\s*[\xa0\s]*€\s*/\s*kk", text)
    result["hoitovastike_eur_month"] = _parse_fin_num(m.group(1)) if m else None

    # Tontin vuokravastike (monthly land rent — vuokratontti properties only)
    # Two formats observed:
    #   "Tontin vuokravastike\n92,40 €/kk"  (own line, space in label)
    #   "Tontinvuokravastike\xa092,40 €/kk" (inline with Mediavastike, \xa0 separator, no space)
    m = (re.search(r"Tontin\s+vuokravastike\s*\n+([\d\xa0\s]+(?:[,.]\d+)?)\s*[\xa0\s]*€\s*/\s*kk", text) or
         re.search(r"Tontinvuokravastike[\xa0\s]+([\d\xa0]+(?:[,.]\d+)?)\s*€\s*/\s*kk", text))
    result["tonttivuokra_eur_month"] = _parse_fin_num(m.group(1)) if m else None

    # Rental / investment status
    rent_m = _RENTED_TERM.search(text)
    if rent_m:
        s = max(0, rent_m.start() - 120)
        e = min(len(text), rent_m.end() + 120)
        result["is_rented_out"]  = True
        result["rented_out_info"] = text[s:e].strip()
    else:
        result["is_rented_out"]  = False
        result["rented_out_info"] = None

    cache[url] = result
    return result


# ---------------------------------------------------------------------------
# Criteria helpers
# ---------------------------------------------------------------------------

def _effective_price(listing: dict) -> float:
    return float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 999_999)


def _loan_acceptable(listing: dict) -> bool:
    loan = listing.get("housing_company_loan_eur")
    if loan is None:
        return True   # unknown — treat as acceptable (already checked individually)
    loan = float(loan)
    if loan == 0:
        return True
    dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
    return dfp > 0 and (loan / dfp) <= LOAN_RATIO_MAX


def _loan_ratio_str(listing: dict) -> str:
    loan = listing.get("housing_company_loan_eur")
    if loan is None:
        return "?"
    loan = float(loan)
    if loan == 0:
        return "0 €"
    dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
    pct = f" ({loan/dfp*100:.0f}%)" if dfp > 0 else ""
    return f"{loan:,.0f} €{pct}".replace(",", " ")


# ---------------------------------------------------------------------------
# Output: CSV
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "address", "district", "city",
    "price_eur", "debt_free_price_eur", "housing_company_loan_eur",
    "room_count", "size_sqm", "floor",
    "year_built", "property_type",
    "pipe_renovation_done", "pipe_renovation_year", "pipe_renovation_info",
    "is_rented_out",
    "monthly_cost_eur", "hoitovastike_eur_month", "tonttivuokra_eur_month",
    "score", "rank", "nearest_stop", "distance_m", "lat", "lon",
    "_search_pass",
    "listing_url",
]


def generate_csv_report(confirmed: list[dict], candidates: list[dict],
                        path: str = "results.csv") -> None:
    rows = confirmed + candidates
    if not rows:
        open(path, "w").write(",".join(CSV_FIELDS) + "\n")
        print(f"Saved → {path}  (empty)")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Saved → {path}  ({len(rows)} rows)")


# ---------------------------------------------------------------------------
# Output: HTML
# ---------------------------------------------------------------------------

def listing_red_flags(l: dict) -> list[tuple[str, str, str]]:
    """Per-listing risk warnings: (text, source_url, source_label)."""
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

    dfp = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
    loan = l.get("housing_company_loan_eur")
    if loan is not None and dfp > 0:
        ratio = float(loan) / dfp
        if ratio > 0.35:
            flags.append((f"Yhtiölainaosuus {ratio*100:.0f}% — rahoitusvastike may spike when interest-only ends",
                           "https://www.taloustaito.fi/koti/isannointiliitto-laski-nain-rajusti-uudiskohteen-rahoitusvastike-voi-nousta/", "taloustaito"))

    hoito = l.get("hoitovastike_eur_month") or 0
    sqm = float(l.get("size_sqm") or 0)
    if hoito and sqm > 0 and hoito / sqm > 6.5:
        flags.append((f"Hoitovastike {hoito/sqm:.1f} €/m²/mo vs 4.74 € Vantaa avg — investigate cause",
                       "https://www.kiinteistoliitto.fi/uutiset/nayta/?id=16859&title=hoitovastikekysely2025", "kiinteistöliitto"))

    return flags


def listing_red_flags_uusimaa(l: dict) -> list[tuple[str, str, str]]:
    """Generic risk warnings for Uusimaa listings (no tram-stop-specific checks)."""
    flags = []

    dfp = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
    loan = l.get("housing_company_loan_eur")
    if loan is not None and dfp > 0:
        ratio = float(loan) / dfp
        if ratio > 0.35:
            flags.append((f"Yhtiölainaosuus {ratio*100:.0f}% — rahoitusvastike may spike when interest-only ends",
                           "https://www.taloustaito.fi/koti/isannointiliitto-laski-nain-rajusti-uudiskohteen-rahoitusvastike-voi-nousta/", "taloustaito"))

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


def generate_html_report(confirmed: list[dict], candidates: list[dict],
                         rented_out: list[dict] = None,
                         uusimaa_rented: list[dict] = None,
                         uusimaa_top5: list[dict] = None,
                         newbuild_pks: list[dict] = None,
                         path=None) -> None:
    if path is None:
        path = _DATA / "index.html"
    rented_out     = rented_out     or []
    uusimaa_rented = uusimaa_rented or []
    uusimaa_top5   = uusimaa_top5   or []
    newbuild_pks   = newbuild_pks   or []
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    def esc(v) -> str:
        return str(v or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def fmt_eur(v) -> str:
        if v is None:
            return "—"
        try:
            return f"{float(v):,.0f} €".replace(",", " ")
        except Exception:
            return str(v)

    def badge(l: dict) -> str:
        tag  = l.get("_search_pass", "")
        yr   = l.get("year_built", "")
        rank = l.get("rank", "")
        sc   = l.get("score", "")
        rank_badge = f'<span class="badge rank">#{esc(str(rank))} &nbsp;{esc(str(sc))}pts</span>' if rank else ""
        rent_badge = '<span class="badge rent">rented out</span>' if l.get("is_rented_out") else ""
        if tag == "new_house_2000plus":
            main_badge = f'<span class="badge new">built {esc(str(yr))}</span>'
        elif tag == "candidate_check_pipe_reno":
            main_badge = f'<span class="badge cand">built {esc(str(yr))} · verify pipe reno</span>'
        else:
            reno_yr = l.get("pipe_renovation_year")
            label   = f"pipe reno {reno_yr}" if reno_yr else "pipe reno ✓"
            main_badge = f'<span class="badge reno">{esc(label)}</span>'
        return rank_badge + main_badge + rent_badge

    def loan_tag(l: dict) -> str:
        loan = l.get("housing_company_loan_eur")
        if loan is None:
            return '<span class="loan loan-unk">loan ?</span>'
        loan = float(loan)
        dfp  = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
        if loan == 0:
            return '<span class="loan loan-ok">loan 0 €</span>'
        pct  = f" {loan/dfp*100:.0f}%" if dfp > 0 else ""
        cls  = "loan-ok" if dfp > 0 and loan/dfp <= LOAN_RATIO_MAX else "loan-bad"
        return f'<span class="loan {cls}">{fmt_eur(loan)}{pct}</span>'

    def make_cards(lst: list[dict]) -> str:
        if not lst:
            return "<p class='empty'>None this run.</p>"
        html = ""
        for l in lst:
            url    = l.get("listing_url") or ""
            addr   = esc(l.get("address", "N/A"))
            dist_s = esc(l.get("district") or "")
            city_s = esc(l.get("city") or "")
            parts  = [p for p in [addr, dist_s, city_s] if p]
            full_addr = ", ".join(parts)

            rank   = l.get("rank", "")
            sc     = l.get("score", "")
            rank_s = f"#{rank} · {sc} pts" if rank else ""

            dfp_v  = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
            price_s = fmt_eur(dfp_v)

            loan   = l.get("housing_company_loan_eur")
            if loan is not None:
                loan_f = float(loan)
                pct    = f" ({loan_f/dfp_v*100:.0f}%)" if dfp_v > 0 and loan_f > 0 else ""
                loan_s = "0 € yhtiölaina" if loan_f == 0 else f"+{fmt_eur(loan_f)} yhtiölaina{pct}"
            else:
                loan_s = "yhtiölaina ?"

            mc     = l.get("monthly_cost_eur")
            hoito  = l.get("hoitovastike_eur_month")
            tontti = l.get("tonttivuokra_eur_month")
            mort_v = monthly_mortgage(max(0.0, dfp_v - DOWN_PAYMENT_EUR))
            if mc is not None:
                total_fixed = mort_v + (float(hoito) if hoito else 0) + (float(tontti) if tontti else 0)
                mc_s = f"{total_fixed:,.0f} €/mo".replace(",", " ")
                mc_html = f'<div class="card-monthly">{mc_s} est.</div>'
            else:
                mc_html = ""

            meta_parts = []
            if l.get("room_count"): meta_parts.append(f"{l['room_count']}h")
            if l.get("size_sqm"):   meta_parts.append(f"{l['size_sqm']} m²")
            if l.get("floor"):      meta_parts.append(f"fl {esc(l['floor'])}")
            if l.get("year_built"): meta_parts.append(str(l["year_built"]))
            meta_s = " · ".join(meta_parts)

            # Badges: age/pipe, tram stop, rented
            tag = l.get("_search_pass", "")
            if tag == "new_house_2000plus":
                status_badge = f'<span class="badge new">built {esc(str(l.get("year_built","")))}</span>'
            elif tag == "candidate_check_pipe_reno":
                status_badge = f'<span class="badge cand">built {esc(str(l.get("year_built","")))} · verify pipe</span>'
            else:
                reno_yr = l.get("pipe_renovation_year")
                label   = f"pipe reno {reno_yr}" if reno_yr else "pipe reno ✓"
                status_badge = f'<span class="badge reno">{esc(label)}</span>'

            stop   = l.get("nearest_stop") or ""
            dist_m = l.get("distance_m")
            tram_b = (f'<span class="badge tram">🚋 {esc(stop)} {round(dist_m) if dist_m is not None else "?"}m</span>'
                      if stop else "")
            rent_b = '<span class="badge rent">rented out</span>' if l.get("is_rented_out") else ""
            badges_html = status_badge + tram_b + rent_b

            stop_note  = _STOP_NOTE.get(stop, "")
            stop_links = _STOP_LINKS.get(stop, [])
            note_html  = ""
            if stop_note:
                links_html = "".join(
                    f'<a href="{esc(u)}" class="stop-link" target="_blank" rel="noopener">{esc(lb)}</a>'
                    for u, lb in stop_links
                )
                note_html = f'<p class="stop-note">{esc(stop_note)}{" " + links_html if links_html else ""}</p>'

            flags = listing_red_flags(l)
            flags_html = ""
            if flags:
                items = "".join(
                    f'<li><span class="rf-text">{esc(txt)}</span>'
                    f'<a href="{esc(u)}" class="rf-link" target="_blank" rel="noopener">{esc(lb)}</a></li>'
                    for txt, u, lb in flags
                )
                flags_html = f'<ul class="risk-flags">{items}</ul>'

            reno = esc(l.get("pipe_renovation_info") or "")
            view_link = f'<a href="{esc(url)}" class="card-view-link" target="_blank">View →</a>' if url else ""
            addr_link = f'<a href="{esc(url)}" target="_blank">{full_addr}</a>' if url else full_addr

            html += f"""
<article class="card">
  <div class="card-top">
    <span class="card-rank">{esc(rank_s)}</span>
    {view_link}
  </div>
  <div class="card-price">{price_s} <span class="card-price-sub">velaton</span></div>
  {mc_html}
  <div class="card-loan">{esc(loan_s)}</div>
  <div class="card-meta">{meta_s}</div>
  <div class="card-address">{addr_link}</div>
  <div class="card-divider"></div>
  <div class="card-badges">{badges_html}</div>
  {note_html}
  {flags_html}
  {"<p class='reno-note'>" + reno + "</p>" if reno else ""}
</article>"""
        return html

    def make_uusimaa_cards(lst: list[dict]) -> str:
        """Uusimaa-view cards — hub proximity + optional tram badge instead of tram stop."""
        if not lst:
            return "<p class='empty'>None this run.</p>"
        html = ""
        for l in lst:
            url    = l.get("listing_url") or ""
            addr   = esc(l.get("address", "N/A"))
            dist_s = esc(l.get("district") or "")
            city_s = esc(l.get("city") or "")
            parts  = [p for p in [addr, dist_s, city_s] if p]
            full_addr = ", ".join(parts)

            rank   = l.get("rank", "")
            sc     = l.get("score", "")
            rank_s = f"#{rank} · {sc} pts" if rank else ""

            dfp_v  = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
            price_s = fmt_eur(dfp_v)

            loan   = l.get("housing_company_loan_eur")
            if loan is not None:
                loan_f = float(loan)
                pct    = f" ({loan_f/dfp_v*100:.0f}%)" if dfp_v > 0 and loan_f > 0 else ""
                loan_s = "0 € yhtiölaina" if loan_f == 0 else f"+{fmt_eur(loan_f)} yhtiölaina{pct}"
            else:
                loan_s = "yhtiölaina ?"

            mc     = l.get("monthly_cost_eur")
            hoito  = l.get("hoitovastike_eur_month")
            tontti = l.get("tonttivuokra_eur_month")
            mort_v = monthly_mortgage(max(0.0, dfp_v - DOWN_PAYMENT_EUR))
            if mc is not None:
                total_fixed = mort_v + (float(hoito) if hoito else 0) + (float(tontti) if tontti else 0)
                mc_s = f"{total_fixed:,.0f} €/mo".replace(",", " ")
                mc_html = f'<div class="card-monthly">{mc_s} est.</div>'
            else:
                mc_html = ""

            meta_parts = []
            if l.get("room_count"): meta_parts.append(f"{l['room_count']}h")
            if l.get("size_sqm"):   meta_parts.append(f"{l['size_sqm']} m²")
            if l.get("floor"):      meta_parts.append(f"fl {esc(l['floor'])}")
            if l.get("year_built"): meta_parts.append(str(l["year_built"]))
            meta_s = " · ".join(meta_parts)

            hub    = l.get("nearest_hub") or "?"
            hdist  = l.get("hub_distance_m")
            hc_km  = l.get("helsinki_central_km")
            mall   = l.get("nearest_mall") or "?"
            mdist  = l.get("mall_distance_m")

            hub_line = (
                f'<div class="card-hub">🚉 {esc(hub)} · {round(hdist) if hdist else "?"}m'
                + (f'  ·  🏙 {hc_km:.1f} km centre' if hc_km else "")
                + '</div>'
            )
            mall_line = (
                f'<div class="card-hub">🛍 {esc(mall)} · {round(mdist) if mdist else "?"}m</div>'
                if mdist else ""
            )

            # Badges: age/pipe, tram proximity (if any), rented
            tag = l.get("_search_pass", "")
            if tag == "new_house_2000plus":
                status_badge = f'<span class="badge new">built {esc(str(l.get("year_built","")))}</span>'
            elif tag == "candidate_check_pipe_reno":
                status_badge = f'<span class="badge cand">built {esc(str(l.get("year_built","")))} · verify pipe</span>'
            else:
                reno_yr = l.get("pipe_renovation_year")
                label   = f"pipe reno {reno_yr}" if reno_yr else "pipe reno ✓"
                status_badge = f'<span class="badge reno">{esc(label)}</span>'

            tb   = l.get("tram_badge")
            tram_b = (f'<span class="badge tram">🚋 {esc(tb["stop"])} {tb["dist"]}m</span>'
                      if tb else "")
            rent_b = '<span class="badge rent">rented out</span>' if l.get("is_rented_out") else ""
            badges_html = status_badge + tram_b + rent_b

            flags = listing_red_flags_uusimaa(l)
            flags_html = ""
            if flags:
                items = "".join(
                    f'<li><span class="rf-text">{esc(txt)}</span>'
                    f'<a href="{esc(u)}" class="rf-link" target="_blank" rel="noopener">{esc(lb)}</a></li>'
                    for txt, u, lb in flags
                )
                flags_html = f'<ul class="risk-flags">{items}</ul>'

            reno = esc(l.get("pipe_renovation_info") or "")
            view_link = f'<a href="{esc(url)}" class="card-view-link" target="_blank">View →</a>' if url else ""
            addr_link = f'<a href="{esc(url)}" target="_blank">{full_addr}</a>' if url else full_addr

            html += f"""
<article class="card">
  <div class="card-top">
    <span class="card-rank">{esc(rank_s)}</span>
    {view_link}
  </div>
  <div class="card-price">{price_s} <span class="card-price-sub">velaton</span></div>
  {mc_html}
  <div class="card-loan">{esc(loan_s)}</div>
  <div class="card-meta">{meta_s}</div>
  <div class="card-address">{addr_link}</div>
  {hub_line}
  {mall_line}
  <div class="card-divider"></div>
  <div class="card-badges">{badges_html}</div>
  {flags_html}
  {"<p class='reno-note'>" + reno + "</p>" if reno else ""}
</article>"""
        return html

    def table_rows(lst: list[dict], row_class: str = "") -> str:
        rows = ""
        for l in lst:
            url   = l.get("listing_url") or ""
            addr  = esc(l.get("address", "—"))
            link  = f'<a href="{esc(url)}" target="_blank">{addr}</a>' if url else addr
            dfp   = l.get("debt_free_price_eur") or l.get("price_eur") or 0
            loan_s = _loan_ratio_str(l)
            tag   = l.get("_search_pass", "")
            status = ("new ≥2000" if tag == "new_house_2000plus"
                      else "check pipe reno" if tag == "candidate_check_pipe_reno"
                      else "pipe reno ✓")
            rows += (
                f'<tr class="{row_class}">'
                f"<td>{link}</td>"
                f"<td>{esc(l.get('district') or '—')}</td>"
                f"<td>{esc(l.get('city') or '—')}</td>"
                f'<td class="num">{fmt_eur(l.get("price_eur"))}</td>'
                f'<td class="num">{fmt_eur(dfp)}</td>'
                f'<td class="num">{loan_s}</td>'
                f"<td>{l.get('room_count','—')}h</td>"
                f"<td>{l.get('size_sqm','—')}</td>"
                f"<td>{l.get('year_built','—')}</td>"
                f"<td>{status}</td>"
                f"</tr>\n"
            )
        return rows

    def uusimaa_table_rows(lst: list[dict], row_class: str = "") -> str:
        rows = ""
        for l in lst:
            url    = l.get("listing_url") or ""
            addr   = esc(l.get("address", "—"))
            link   = f'<a href="{esc(url)}" target="_blank">{addr}</a>' if url else addr
            dfp    = l.get("debt_free_price_eur") or l.get("price_eur") or 0
            loan_s = _loan_ratio_str(l)
            tag    = l.get("_search_pass", "")
            status = ("new ≥2000" if tag == "new_house_2000plus"
                      else "check pipe reno" if tag == "candidate_check_pipe_reno"
                      else "pipe reno ✓")
            hub    = l.get("nearest_hub") or "—"
            hdist  = l.get("hub_distance_m")
            hub_str = f"{esc(hub)} {round(hdist)}m" if hdist else esc(hub)
            sc     = l.get("score", "—")
            rows += (
                f'<tr class="{row_class}">'
                f"<td>{link}</td>"
                f"<td>{esc(l.get('district') or '—')}</td>"
                f"<td>{esc(l.get('city') or '—')}</td>"
                f'<td class="num">{fmt_eur(l.get("price_eur"))}</td>'
                f'<td class="num">{fmt_eur(dfp)}</td>'
                f'<td class="num">{loan_s}</td>'
                f"<td>{l.get('room_count','—')}h</td>"
                f"<td>{l.get('size_sqm','—')}</td>"
                f"<td>{l.get('year_built','—')}</td>"
                f"<td>{hub_str}</td>"
                f'<td class="num">{sc}</td>'
                f"</tr>\n"
            )
        return rows

    def sec(title: str, note: str, lst: list, cls: str = "") -> str:
        if not lst:
            return ""
        return f"""
<section class="sec {cls}">
  <h2 class="sec-title">{title}</h2>
  {"<p class='sec-note'>" + note + "</p>" if note else ""}
  <div class="grid">{make_cards(lst)}</div>
</section>"""

    def uu_sec(title: str, note: str, lst: list, cls: str = "") -> str:
        if not lst:
            return ""
        return f"""
<section class="sec {cls}">
  <h2 class="sec-title">{title}</h2>
  {"<p class='sec-note'>" + note + "</p>" if note else ""}
  <div class="grid">{make_uusimaa_cards(lst)}</div>
</section>"""

    # ── Tram display tiers — rented excluded from other sections to avoid duplication
    rented_cards   = rented_out
    new_cards      = [l for l in confirmed  if l.get("_search_pass") == "new_house_2000plus"
                      and not l.get("is_rented_out")]
    pipe_cards     = [l for l in confirmed  if (l.get("_search_pass") or "").startswith("pipe_reno_")
                      and not l.get("is_rented_out")]
    cand_cards     = [l for l in candidates if not l.get("is_rented_out")]

    tram_table_body = table_rows(confirmed, "row-confirmed") + table_rows(candidates, "row-cand")
    tram_cards_body = (
        sec("Rented Out — immediate rental income",
            "Currently tenanted. Rental income offsets costs from day one.",
            rented_cards, "sec-rented") +
        sec("New Builds (≥ 2000)",
            "Built 2000 or later — no pipe renovation concern.",
            new_cards, "sec-new") +
        sec("Older Builds — Pipe Renovation Done",
            "Pre-2000 buildings with confirmed completed pipe renovation.",
            pipe_cards, "sec-reno") +
        sec("Candidates — Pipe Renovation Unverified",
            "Older buildings where pipe renovation status could not be confirmed automatically. Verify manually before deciding.",
            cand_cards, "sec-cand")
    )

    # ── Uusimaa display tiers
    uu_table_body = (
        uusimaa_table_rows(uusimaa_rented, "row-confirmed") +
        uusimaa_table_rows(uusimaa_top5, "row-cand")
    )
    uu_cards_body = (
        uu_sec("Rented Out — Helsinki / Espoo / Vantaa",
               "For-sale apartments with an existing tenant. Immediate rental income from day one.",
               uusimaa_rented, "sec-rented") +
        uu_sec(f"Watch List — Top {UUSIMAA_TOP_UNRENTED} Unrented",
               "Highest-scoring unrented apartments in Helsinki/Espoo/Vantaa by hub-proximity model. Verify pipe reno and local market before deciding.",
               uusimaa_top5, "sec-new")
    )

    # ── New build display
    nb_table_body = uusimaa_table_rows(newbuild_pks)
    nb_cards_body = uu_sec(
        f"PKS New Construction — Top {len(newbuild_pks)} (1 per building)",
        f"Newly built / under-construction apartments in Helsinki, Espoo, Vantaa. "
        f"Price ≤ {UUSIMAA_PRICE_MAX:,} €, loan ≤ {int(UUSIMAA_LOAN_RATIO_MAX*100)}%. "
        "Deduplicated to one listing per building, then top scored by hub proximity.",
        newbuild_pks, "sec-new"
    )

    loc_names = ", ".join(l[2] for l in TRAMLINE_LOCATIONS)

    html = f"""<!DOCTYPE html>
<html lang="fi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oikotie — asuntoanalyysi</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: #f4f5f7; color: #1a1a2e; padding: 2rem 1rem; }}
header {{ max-width: 1100px; margin: 0 auto 1.5rem; }}
header h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: .25rem; }}
header p {{ color: #555; font-size: .85rem; }}
.criteria {{ max-width: 1100px; margin: 0 auto 1.5rem;
  background: #e8f4fd; border-left: 4px solid #2196f3;
  padding: .75rem 1rem; border-radius: 0 6px 6px 0;
  font-size: .82rem; color: #333; line-height: 1.7; }}
.tabs {{ max-width: 1100px; margin: 0 auto 1rem; display: flex; gap: .5rem; }}
.tab-btn {{ padding: .45rem 1.1rem; border: 1px solid #ccc; background: #fff;
  border-radius: 6px; cursor: pointer; font-size: .85rem; font-weight: 500; }}
.tab-btn.active {{ background: #1565c0; color: #fff; border-color: #1565c0; }}
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem; max-width: 1100px; margin: 0 auto; }}
/* ── Card ── */
.card {{ background: #fff; border-radius: 12px; padding: 18px;
  box-shadow: 0 1px 4px rgba(0,0,0,.07); display: flex; flex-direction: column; gap: .35rem; }}
.card-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: .1rem; }}
.card-rank {{ font-size: .73rem; font-weight: 700; color: #999; letter-spacing: .02em; text-transform: uppercase; }}
.card-view-link {{ font-size: .78rem; color: #1565c0; text-decoration: none; font-weight: 600; flex-shrink: 0; }}
.card-view-link:hover {{ text-decoration: underline; }}
.card-price {{ font-size: 1.55rem; font-weight: 700; letter-spacing: -.5px; color: #1a1a2e; line-height: 1.1; }}
.card-price-sub {{ font-size: .82rem; font-weight: 400; color: #999; margin-left: 3px; }}
.card-monthly {{ font-size: 1.0rem; font-weight: 600; color: #1565c0; }}
.card-loan {{ font-size: .78rem; color: #777; }}
.card-meta {{ font-size: .8rem; color: #666; margin-top: .05rem; }}
.card-address {{ font-size: .84rem; color: #444; }}
.card-address a {{ color: #1a1a2e; text-decoration: none; font-weight: 500; }}
.card-address a:hover {{ color: #1565c0; }}
.card-hub {{ font-size: .78rem; color: #555; }}
.card-divider {{ border: none; border-top: 1px solid #eee; margin: .2rem 0; }}
.card-badges {{ display: flex; gap: .3rem; flex-wrap: wrap; }}
.badge {{ font-size: .7rem; font-weight: 600; padding: 2px 8px;
  border-radius: 99px; white-space: nowrap; }}
.badge.new  {{ background: #d4f4e0; color: #1a6b3a; }}
.badge.reno {{ background: #fde8d4; color: #7a3a0a; }}
.badge.cand {{ background: #fff3cd; color: #7a5a00; }}
.badge.rent {{ background: #e8d4f4; color: #4a1a6b; }}
.badge.tram {{ background: #e3f2fd; color: #0d47a1; }}
.stop-note {{ font-size: .75rem; color: #2a6496; background: #eef5fb;
  border-left: 3px solid #2a6496; padding: .2rem .5rem; border-radius: 0 3px 3px 0; }}
.stop-link {{ font-size: .68rem; color: #2a6496; border: 1px solid #2a6496;
  padding: 0 .35rem; border-radius: 3px; text-decoration: none; margin-left: .3rem; white-space: nowrap; }}
.stop-link:hover {{ background: #2a6496; color: #fff; }}
.risk-flags {{ list-style: none; margin: .1rem 0; padding: 0; display: flex; flex-direction: column; gap: .2rem; }}
.risk-flags li {{ font-size: .72rem; background: #fff5f5; border-left: 3px solid #c0392b;
  padding: .2rem .5rem; border-radius: 0 3px 3px 0;
  display: flex; justify-content: space-between; align-items: baseline; gap: .4rem; }}
.rf-text {{ color: #7a1010; flex: 1; }}
.rf-link {{ font-size: .66rem; color: #c0392b; border: 1px solid #c0392b;
  padding: 0 .3rem; border-radius: 3px; text-decoration: none; white-space: nowrap; flex-shrink: 0; }}
.rf-link:hover {{ background: #c0392b; color: #fff; }}
.reno-note {{ font-size: .72rem; color: #888; border-top: 1px solid #eee;
  padding-top: .3rem; line-height: 1.4; }}
/* ── Table ── */
.tbl-wrap {{ max-width: 1100px; margin: 0 auto; overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: .82rem; }}
th {{ background: #1565c0; color: #fff; padding: .5rem .75rem;
  text-align: left; cursor: pointer; white-space: nowrap; user-select: none; }}
th:hover {{ background: #1976d2; }}
td {{ padding: .45rem .75rem; border-bottom: 1px solid #e8e8e8; vertical-align: top; }}
td a {{ color: #1565c0; text-decoration: none; }}
td a:hover {{ text-decoration: underline; }}
.num {{ text-align: right; white-space: nowrap; }}
tr.row-confirmed:hover {{ background: #f0f8ff; }}
tr.row-cand {{ background: #fffdf0; }}
tr.row-cand:hover {{ background: #fff8dc; }}
.sort-asc::after {{ content: " ▲"; }}
.sort-desc::after {{ content: " ▼"; }}
/* ── Sections ── */
.sec {{ margin-top: 2rem; }}
.sec-title {{ font-size: 1rem; font-weight: 700; margin: 0 auto .3rem; max-width: 1100px; }}
.sec-note  {{ font-size: .8rem; color: #888; margin: 0 auto .75rem; max-width: 1100px; }}
.sec-rented .sec-title {{ color: #4a1a6b; }}
.sec-new    .sec-title {{ color: #1a6b3a; }}
.sec-reno   .sec-title {{ color: #7a3a0a; }}
.sec-cand   .sec-title {{ color: #7a5a00; }}
.empty {{ text-align: center; color: #888; padding: 2rem; }}
/* ── Market risks ── */
.market-risks {{ max-width: 1100px; margin: .75rem auto; background: #fffbf0;
  border: 1px solid #e6c84a; border-radius: 8px; overflow: hidden; }}
.market-risks summary {{ padding: .6rem 1rem; cursor: pointer; font-size: .85rem;
  font-weight: 600; color: #7a5a00; user-select: none; }}
.market-risks summary:hover {{ background: #fff3cd; }}
.mr-grid {{ display: flex; flex-direction: column; gap: .3rem; padding: .5rem 1rem .75rem; }}
.mr-item {{ display: flex; align-items: baseline; gap: .5rem; font-size: .78rem;
  background: #fff; border-radius: 4px; padding: .3rem .5rem; }}
.mr-sev {{ font-size: .66rem; font-weight: 700; padding: 1px 5px; border-radius: 3px;
  white-space: nowrap; flex-shrink: 0; }}
.mr-opp  .mr-sev {{ background: #d4f4e0; color: #1a6b3a; }}
.mr-high .mr-sev {{ background: #ffe0e0; color: #8b0000; }}
.mr-med  .mr-sev {{ background: #fff3cd; color: #7a5a00; }}
.mr-text {{ flex: 1; color: #444; line-height: 1.4; }}
.mr-item a {{ font-size: .68rem; color: #7a5a00; border: 1px solid #c8a800;
  padding: 0 .3rem; border-radius: 3px; text-decoration: none; white-space: nowrap; flex-shrink: 0; }}
.mr-item a:hover {{ background: #c8a800; color: #fff; }}
/* ── Mode nav ── */
.mode-nav {{ max-width: 1100px; margin: 0 auto 1.5rem; display: flex; gap: .5rem;
  border-bottom: 2px solid #d0d0d8; padding-bottom: .6rem; }}
.mode-btn {{ padding: .55rem 1.5rem; border: 2px solid transparent; background: #f0f0f4;
  border-radius: 8px; cursor: pointer; font-size: .9rem; font-weight: 600; color: #555; }}
.mode-btn.active {{ background: #1565c0; color: #fff; border-color: #1565c0; }}
</style>
</head>
<body>
<div class="mode-nav">
  <button class="mode-btn active" onclick="showMode('tram', this)">🚋 Vantaan Ratikka</button>
  <button class="mode-btn" onclick="showMode('uusimaa', this)">🏘 PKS Vuokratut</button>
  <button class="mode-btn" onclick="showMode('newbuild', this)">🏗 PKS Uutuudet</button>
</div>
<!-- ═══════════════════════════════════════════════════════ TRAM VIEW -->
<div id="mode-tram">
<header>
  <h1>Oikotie — asunnot lähellä Vantaan ratikkaa</h1>
  <p>Generated {run_time} &nbsp;·&nbsp;
     {len(rented_cards)} rented out &nbsp;·&nbsp;
     {len(new_cards)} new builds &nbsp;·&nbsp;
     {len(pipe_cards)} pipe reno done &nbsp;·&nbsp;
     {len(cand_cards)} candidates &nbsp;·&nbsp;
     ranked by score</p>
</header>
<div class="criteria">
  <strong>Filters:</strong>
  Free-market (habitationType=1) · velaton hinta ≤ {PRICE_MAX:,} € ·
  loan ≤ {int(LOAN_RATIO_MAX*100)}% of debt-free price ·
  Built ≥ 2000 <em>or</em> older with completed pipe renovation ·
  1980–1995 builds without confirmed pipe reno excluded ·
  ≤ {MAX_STOP_DIST_M} m from a tram stop
</div>
<details class="market-risks">
  <summary>⚠️ Market &amp; project risk factors (click to expand)</summary>
  <div class="mr-grid">
    <div class="mr-item mr-high">
      <span class="mr-sev">HIGH</span>
      <span class="mr-text">Vantaa apartment prices have been the worst-performing major city 2024–2025 (–9.1% peak YoY, –5.2% May 2025)</span>
      <a href="https://www.helsinkitimes.fi/finland/finland-news/domestic/27245-housing-prices-drop-again-in-may-with-vantaa-hit-hardest.html" target="_blank" rel="noopener">helsinkitimes</a>
    </div>
    <div class="mr-item mr-high">
      <span class="mr-sev">HIGH</span>
      <span class="mr-text">Rental vacancy in HMA tripled 2020–2024; Vantaa occupancy declined Q4 2025 while Helsinki/Espoo held steady</span>
      <a href="https://innagroup.fi/en/news/market-reviews/residential-rental-market-q4-2025-seasonal-fluctuations-and-economic-conditions-reflected-in-q4-outlook-for-2026-cautiously-upward/" target="_blank" rel="noopener">INNA Q4 2025</a>
    </div>
    <div class="mr-item mr-high">
      <span class="mr-sev">HIGH</span>
      <span class="mr-text">Tram budget already overrun 16%+ (€647M → €750M) before construction started; Vantaa in €79.7M fiscal deficit with €544M tram commitment</span>
      <a href="https://www.mtvuutiset.fi/artikkeli/vantaan-ratikan-hinta-noussut-750-miljoonaan-selvasti-muita-kaupunkeja-kalliimpi/9246426" target="_blank" rel="noopener">MTV Uutiset</a>
    </div>
    <div class="mr-item mr-high">
      <span class="mr-sev">HIGH</span>
      <span class="mr-text">New-build oversupply: YIT had 1,359 completed unsold units (full year inventory) in 2024; developers offering concessions, competing directly with private investors</span>
      <a href="https://www.salkunrakentaja.fi/2024/05/yit-myymattomat-asunnot/" target="_blank" rel="noopener">salkunrakentaja</a>
    </div>
    <div class="mr-item mr-med">
      <span class="mr-sev">MED</span>
      <span class="mr-text">Tram opens at earliest 2029 — asking prices already reflect "tram premium" but buyers bear 3+ years of financing with no transit benefit</span>
      <a href="https://ratikka.vantaa.fi/en/traffic-and-transport/vantaa-light-rail/information-about-vantaa-light-rail" target="_blank" rel="noopener">ratikka.vantaa.fi</a>
    </div>
    <div class="mr-item mr-med">
      <span class="mr-sev">MED</span>
      <span class="mr-text">Finnish construction sector: 381 bankruptcies in Jan 2025 alone — risk of developer insolvency on pre-completion new builds</span>
      <a href="https://www.rakennuslehti.fi/2025/02/konkurssiin-haettiin-tammikuussa-kymmenia-rakennusalan-yrityksia/" target="_blank" rel="noopener">rakennuslehti</a>
    </div>
  </div>
</details>
<div class="tabs">
  <button class="tab-btn active" onclick="showTab('tram-cards','mode-tram',this)">Cards</button>
  <button class="tab-btn" onclick="showTab('tram-table','mode-tram',this)">Table / Analysis</button>
</div>
<div id="tab-tram-cards" class="tab-panel active">
  {tram_cards_body}
</div>
<div id="tab-tram-table" class="tab-panel">
  <div class="tbl-wrap">
    <table id="tram-table">
      <thead><tr>
        <th onclick="sortTable('tram-table',0)">Address</th>
        <th onclick="sortTable('tram-table',1)">District</th>
        <th onclick="sortTable('tram-table',2)">City</th>
        <th onclick="sortTable('tram-table',3)">Price</th>
        <th onclick="sortTable('tram-table',4)">Velaton</th>
        <th onclick="sortTable('tram-table',5)">Loan</th>
        <th onclick="sortTable('tram-table',6)">Rooms</th>
        <th onclick="sortTable('tram-table',7)">m²</th>
        <th onclick="sortTable('tram-table',8)">Year</th>
        <th onclick="sortTable('tram-table',9)">Status</th>
      </tr></thead>
      <tbody>{tram_table_body}</tbody>
    </table>
  </div>
</div>
</div><!-- /mode-tram -->

<!-- ═══════════════════════════════════════════════════ UUSIMAA VIEW -->
<div id="mode-uusimaa" style="display:none">
<header>
  <h1>Oikotie — sijoitusasunnot PKS (Helsinki · Espoo · Vantaa)</h1>
  <p>Generated {run_time} &nbsp;·&nbsp;
     {len(uusimaa_rented)} rented out (all shown) &nbsp;·&nbsp;
     {len(uusimaa_top5)} unrented watch list &nbsp;·&nbsp;
     scored: hub · central · mall · quality</p>
</header>
<div class="criteria">
  <strong>Filters:</strong>
  Free-market · velaton hinta ≤ {UUSIMAA_PRICE_MAX:,} € ·
  loan ≤ {int(UUSIMAA_LOAN_RATIO_MAX*100)}% · Built ≥ 2000 <em>or</em> older with pipe reno ·
  1980–1995 without confirmed reno excluded ·
  Rented-out: all shown &nbsp;·&nbsp; Unrented: top {UUSIMAA_TOP_UNRENTED} by score ·
  🚋 tram badge if ≤ {MAX_STOP_DIST_M} m from Vantaan ratikka stop
</div>
<details class="market-risks">
  <summary>📊 PKS market signals &amp; risks (click to expand)</summary>
  <div class="mr-grid">
    <div class="mr-item mr-opp">
      <span class="mr-sev">OPP</span>
      <span class="mr-text">Occupancy recovering — Helsinki metro rental occupancy 94% in Q3 2025, best since H1 2020; oversupply gradually melting away</span>
      <a href="https://rettamanagement.fi/en/ajankohtaista/releases/finnish-residential-rental-market-q3-2025-strong-results-as-expected/" target="_blank" rel="noopener">Retta Q3 2025</a>
    </div>
    <div class="mr-item mr-opp">
      <span class="mr-sev">OPP</span>
      <span class="mr-text">Gross yields 5–7% in transit-connected PKS suburbs; HMA identified as clear growth area 2025–2026; new construction halted → supply constraint building</span>
      <a href="https://investropa.com/blogs/news/helsinki-rental-yields" target="_blank" rel="noopener">Investropa 2026</a>
    </div>
    <div class="mr-item mr-opp">
      <span class="mr-sev">OPP</span>
      <span class="mr-text">Prices near historical lows — buyers market; sellers negotiating; current correction may prove excellent entry if bought below replacement cost</span>
      <a href="https://kasvutalous.fi/%F0%9F%8F%A0-asuntomarkkinoiden-toipuminen-suomessa-mita-tapahtuu-vuonna-2026/" target="_blank" rel="noopener">kasvutalous.fi</a>
    </div>
    <div class="mr-item mr-med">
      <span class="mr-sev">RISK</span>
      <span class="mr-text">Rental supply still abundant — non-subsidized rents declined –1.3% recently; upward rent pressure will take more time to materialize</span>
      <a href="https://rettamanagement.fi/en/ajankohtaista/releases/finnish-residential-rental-market-q3-2025-strong-results-as-expected/" target="_blank" rel="noopener">Retta Management</a>
    </div>
    <div class="mr-item mr-med">
      <span class="mr-sev">RISK</span>
      <span class="mr-text">Price uncertainty — realistic planning range for Helsinki next 12 months: –3% to +2%; small further dip in early 2026 remains plausible</span>
      <a href="https://investropa.com/blogs/news/helsinki-good-time" target="_blank" rel="noopener">Investropa 2026</a>
    </div>
    <div class="mr-item mr-high">
      <span class="mr-sev">RISK</span>
      <span class="mr-text">Pipe renovation liability in 1975–1995 Helsinki/Espoo/Vantaa stock — major capital expenditure risk; confirm renovation status before any offer</span>
      <a href="https://www.kiinteistoliitto.fi/" target="_blank" rel="noopener">kiinteistöliitto</a>
    </div>
    <div class="mr-item mr-med">
      <span class="mr-sev">RISK</span>
      <span class="mr-text">Interest rate sensitivity — Euribor 12M at 2.2–2.3%; any reversal upward directly compresses net yield on leveraged properties</span>
      <a href="https://www.sijoittaja.fi/424295/asuntosijoittaminen-vuonna-2026/" target="_blank" rel="noopener">sijoittaja.fi</a>
    </div>
  </div>
</details>
<div class="tabs">
  <button class="tab-btn active" onclick="showTab('uu-cards','mode-uusimaa',this)">Cards</button>
  <button class="tab-btn" onclick="showTab('uu-table','mode-uusimaa',this)">Table / Analysis</button>
</div>
<div id="tab-uu-cards" class="tab-panel active">
  {uu_cards_body}
</div>
<div id="tab-uu-table" class="tab-panel">
  <div class="tbl-wrap">
    <table id="uu-table">
      <thead><tr>
        <th onclick="sortTable('uu-table',0)">Address</th>
        <th onclick="sortTable('uu-table',1)">District</th>
        <th onclick="sortTable('uu-table',2)">City</th>
        <th onclick="sortTable('uu-table',3)">Price</th>
        <th onclick="sortTable('uu-table',4)">Velaton</th>
        <th onclick="sortTable('uu-table',5)">Loan</th>
        <th onclick="sortTable('uu-table',6)">Rooms</th>
        <th onclick="sortTable('uu-table',7)">m²</th>
        <th onclick="sortTable('uu-table',8)">Year</th>
        <th onclick="sortTable('uu-table',9)">Nearest Hub</th>
        <th onclick="sortTable('uu-table',10)">Score</th>
      </tr></thead>
      <tbody>{uu_table_body}</tbody>
    </table>
  </div>
</div>
</div><!-- /mode-uusimaa -->

<!-- ════════════════════════════════════════════ NEW BUILD VIEW -->
<div id="mode-newbuild" style="display:none">
  <h1>Oikotie — Uudisasunnot PKS (Helsinki · Espoo · Vantaa)</h1>
  <p style="margin:.5rem 0 1rem;color:#555">
     {len(newbuild_pks)} listings &nbsp;·&nbsp;
     velaton hinta ≤ {UUSIMAA_PRICE_MAX:,} € · loan ≤ {int(UUSIMAA_LOAN_RATIO_MAX*100)}% ·
     Sorted by hub-proximity score
  </p>
  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('nb-cards','mode-newbuild',this)">Cards</button>
    <button class="tab-btn" onclick="showTab('nb-table','mode-newbuild',this)">Table / Analysis</button>
  </div>
  <div id="nb-cards" class="tab-panel active">
    {nb_cards_body}
  </div>
  <div id="nb-table" class="tab-panel" style="display:none">
    <table id="nb-table-el" class="results-table">
      <thead><tr>
        <th onclick="sortTable('nb-table-el',0)">Rank</th>
        <th onclick="sortTable('nb-table-el',1)">Address</th>
        <th onclick="sortTable('nb-table-el',2)">Price €</th>
        <th onclick="sortTable('nb-table-el',3)">m²</th>
        <th onclick="sortTable('nb-table-el',4)">Year</th>
        <th onclick="sortTable('nb-table-el',5)">Monthly €</th>
        <th onclick="sortTable('nb-table-el',6)">Hub</th>
        <th onclick="sortTable('nb-table-el',7)">Score</th>
      </tr></thead>
      <tbody>{nb_table_body}</tbody>
    </table>
  </div>
</div><!-- /mode-newbuild -->

<script>
function showMode(name, btn) {{
  document.querySelectorAll('[id^="mode-"]').forEach(v => v.style.display = 'none');
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('mode-' + name).style.display = 'block';
  btn.classList.add('active');
}}
function showTab(tabId, modeId, btn) {{
  const mode = document.getElementById(modeId);
  mode.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  mode.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tabId).classList.add('active');
  btn.classList.add('active');
}}
const _sortState = {{}};
function sortTable(tableId, col) {{
  const st = _sortState[tableId] || {{c: -1, d: 1}};
  if (st.c === col) st.d *= -1; else {{ st.c = col; st.d = 1; }}
  _sortState[tableId] = st;
  const tbl = document.getElementById(tableId);
  const tb  = tbl.querySelector('tbody');
  const rows = Array.from(tb.querySelectorAll('tr'));
  tbl.querySelectorAll('th').forEach(h => h.classList.remove('sort-asc','sort-desc'));
  tbl.querySelectorAll('th')[col].classList.add(st.d === 1 ? 'sort-asc' : 'sort-desc');
  rows.sort((a, b) => {{
    const av = a.cells[col].innerText.replace(/[€ \s,%]/g,'');
    const bv = b.cells[col].innerText.replace(/[€ \s,%]/g,'');
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return (an - bn) * st.d;
    return av.localeCompare(bv, 'fi') * st.d;
  }});
  rows.forEach(r => tb.appendChild(r));
}}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Saved → {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    force = "--force" in sys.argv

    # ── Fast path: serve from results cache ──────────────────────────────
    if not force:
        cached = _load_results_cache()
        if cached is not None:
            print(f"Using results cache (saved {cached['timestamp']}).")
            print("Pass --force to bypass and run the full pipeline.\n")
            confirmed       = cached["confirmed"]
            candidates      = cached["candidates"]
            tram_rented_out = cached["tram_rented_out"]
            uusimaa_rented  = cached["uusimaa_rented"]
            uusimaa_top5    = cached["uusimaa_top5"]
            uusimaa_passing = cached["uusimaa_passing"]
            newbuild_pks    = cached.get("newbuild_pks", [])
            with open(_DATA / "results_tram.json", "w", encoding="utf-8") as fh:
                json.dump(confirmed + candidates, fh, ensure_ascii=False, indent=2)
            with open(_DATA / "results_uusimaa.json", "w", encoding="utf-8") as fh:
                json.dump(uusimaa_passing, fh, ensure_ascii=False, indent=2)
            with open(_DATA / "results_newbuild.json", "w", encoding="utf-8") as fh:
                json.dump(newbuild_pks, fh, ensure_ascii=False, indent=2)
            generate_csv_report(confirmed, candidates, path=str(_DATA / "results_tram.csv"))
            generate_csv_report(uusimaa_rented, uusimaa_top5, path=str(_DATA / "results_uusimaa.csv"))
            generate_html_report(confirmed, candidates, tram_rented_out,
                                 uusimaa_rented, uusimaa_top5, newbuild_pks)
            return

    from playwright.sync_api import sync_playwright

    print("Starting Playwright (WebKit) …")

    cache = _load_cache()

    with sync_playwright() as pw:
        browser = pw.webkit.launch(headless=True)
        page    = browser.new_page()

        # ── Tram pipeline: scrape ────────────────────────────────────────
        print(f"\nTRAM PIPELINE: {len(TRAMLINE_LOCATIONS)} districts, price ≤ {PRICE_MAX:,} €")

        tram_raw: list[dict] = []
        seen_urls: set[str] = set()
        total_pages = None
        p = 1
        while True:
            print(f"  Page {p}" + (f"/{total_pages}" if total_pages else "") + " …", end=" ", flush=True)
            listings, total, total_pages = scrape_search_page(page, p)
            new = 0
            for l in listings:
                u = l.get("listing_url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    tram_raw.append(l)
                    new += 1
            print(f"{new} new  (total so far: {len(tram_raw)}/{total})")
            if p >= total_pages:
                break
            p += 1

        print(f"\nTram raw listings (deduped): {len(tram_raw)}")
        tram_initial = [l for l in tram_raw if (l.get("price_eur") or 999_999) <= PRICE_MAX]
        print(f"After initial filter (≤{PRICE_MAX:,} €): {len(tram_initial)}")

        tram_to_check = [l for l in tram_initial if l.get("listing_url")][:MAX_DETAIL_CHECKS]
        if tram_to_check:
            print(f"\n  Fetching details for {len(tram_to_check)} tram listings …")
            newly = 0
            for idx, listing in enumerate(tram_to_check, 1):
                url = listing["listing_url"]
                cached = url in cache
                label  = listing.get("address") or url.split("/")[-1]
                print(f"  [{idx:2d}/{len(tram_to_check)}] {'(cache) ' if cached else ''}{label}")
                details = fetch_listing_details(page, url, cache)
                listing.update({k: v for k, v in details.items() if v is not None})
                if not cached:
                    newly += 1
            _save_cache(cache)
            print(f"  {newly} fresh fetches, {len(tram_to_check)-newly} from cache")

        # ── Uusimaa pipeline: scrape ─────────────────────────────────────
        print(f"\nPKS PIPELINE: Helsinki / Espoo / Vantaa, price ≤ {UUSIMAA_PRICE_MAX:,} €")

        uu_raw: list[dict] = []
        uu_seen: set[str] = set()
        uu_pages = None
        p = 1
        while True:
            print(f"  Page {p}" + (f"/{uu_pages}" if uu_pages else "") + " …", end=" ", flush=True)
            listings, total, uu_pages = scrape_search_page(
                page, p,
                url_builder=build_uusimaa_search_url,
                link_selector=_UUSIMAA_LINK_SELECTOR,
            )
            new = 0
            for l in listings:
                u = l.get("listing_url", "")
                if u and u not in uu_seen:
                    uu_seen.add(u)
                    uu_raw.append(l)
                    new += 1
            print(f"{new} new  (total so far: {len(uu_raw)}/{total})")
            if p >= uu_pages:
                break
            p += 1

        print(f"\nUusimaa raw listings (deduped): {len(uu_raw)}")
        uu_initial = [l for l in uu_raw if (l.get("price_eur") or 999_999) <= UUSIMAA_PRICE_MAX]
        print(f"After initial filter (≤{UUSIMAA_PRICE_MAX:,} €): {len(uu_initial)}")

        uu_to_check = [l for l in uu_initial if l.get("listing_url")][:MAX_DETAIL_CHECKS]
        if uu_to_check:
            print(f"\n  Fetching details for {len(uu_to_check)} Uusimaa listings …")
            newly = 0
            for idx, listing in enumerate(uu_to_check, 1):
                url = listing["listing_url"]
                cached = url in cache
                label  = listing.get("address") or url.split("/")[-1]
                print(f"  [{idx:2d}/{len(uu_to_check)}] {'(cache) ' if cached else ''}{label}")
                details = fetch_listing_details(page, url, cache)
                listing.update({k: v for k, v in details.items() if v is not None})
                if not cached:
                    newly += 1
            _save_cache(cache)
            print(f"  {newly} fresh fetches, {len(uu_to_check)-newly} from cache")

        # ── New build pipeline: scrape (inside browser context) ──────────
        print(f"\nNEWBUILD PIPELINE: PKS new construction, price ≤ {UUSIMAA_PRICE_MAX:,} €")
        nb_raw:  list[dict] = []
        nb_seen: set[str]   = set()
        nb_pages = None
        p = 1
        while nb_pages is None or p <= nb_pages:
            listings, total, nb_pages = scrape_search_page(
                page, p, url_builder=build_newbuild_search_url,
                link_selector=_NEWBUILD_LINK_SELECTOR,
            )
            new = [l for l in listings if l.get("listing_url") not in nb_seen]
            for l in new:
                nb_seen.add(l.get("listing_url", ""))
            nb_raw.extend(new)
            print(f"  Page {p}/{nb_pages} … {len(new)} new  (total so far: {len(nb_raw)}/{total})")
            if not new:
                break
            p += 1

        nb_initial = [l for l in nb_raw if (l.get("price_eur") or 999_999) <= UUSIMAA_PRICE_MAX]
        print(f"New build raw: {len(nb_raw)}  |  after price filter: {len(nb_initial)}")

        nb_to_check = [l for l in nb_initial if l.get("listing_url")]
        if nb_to_check:
            print(f"\n  Fetching details for {len(nb_to_check)} new build listings …")
            nb_newly = 0
            for idx, listing in enumerate(nb_to_check, 1):
                url = listing["listing_url"]
                cached_entry = url in cache
                label = listing.get("address") or url.split("/")[-1]
                print(f"  [{idx}/{len(nb_to_check)}] {'(cache) ' if cached_entry else ''}{label}")
                details = fetch_listing_details(page, url, cache)
                listing.update({k: v for k, v in details.items() if v is not None})
                if not cached_entry:
                    nb_newly += 1
            _save_cache(cache)
            print(f"  {nb_newly} fresh fetches, {len(nb_to_check)-nb_newly} from cache")

        browser.close()

    # ── Tram: geocode + filter + score ───────────────────────────────────
    geo_cache = _load_geo_cache()
    tram_geocoded: list[dict] = []
    fresh_geo = 0

    print(f"\n  Geocoding {len(tram_to_check)} tram listings (≤{MAX_STOP_DIST_M} m from stop) …")
    for listing in tram_to_check:
        url  = listing.get("listing_url", "")
        addr = listing.get("address", "")
        city = listing.get("city", "")
        # Fast path: geo already stored in listing_cache from a prior run
        if url and url in cache and cache[url].get("lat") is not None:
            entry = cache[url]
            listing.update({k: entry[k] for k in ("lat", "lon", "nearest_stop", "distance_m") if k in entry})
            if listing.get("distance_m", 9999) <= MAX_STOP_DIST_M:
                tram_geocoded.append(listing)
            continue
        was_cached = f"{addr}, {city}, Finland" in geo_cache
        coords = geocode_address(addr, city, geo_cache)
        if not was_cached:
            fresh_geo += 1
            time.sleep(1.5)
        if coords is None:
            listing.update({"lat": None, "lon": None, "nearest_stop": None, "distance_m": None})
            tram_geocoded.append(listing)
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
            tram_geocoded.append(listing)

    _save_geo_cache(geo_cache)
    print(f"  {fresh_geo} fresh geocodes, {len(tram_to_check)-fresh_geo} from cache")
    print(f"  Within {MAX_STOP_DIST_M} m of a stop: {len(tram_geocoded)}/{len(tram_to_check)}")

    confirmed: list[dict] = []
    candidates: list[dict] = []
    for l in tram_geocoded:
        if _effective_price(l) > PRICE_MAX:
            continue
        if not _loan_acceptable(l):
            continue
        is_old    = (l.get("year_built") or 9999) < 2000
        pipe_done = _eval_pipe_done(l.get("pipe_renovation_info"), l.get("pipe_renovation_year"))
        year      = l.get("year_built") or 0
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

    for l in confirmed + candidates:
        l["monthly_cost_eur"] = round(monthly_cost_eur(l), 2)
        l["score"]            = score_listing(l)

    def _tier(l: dict) -> int:
        if l.get("is_rented_out"):                          return 0
        if l.get("_search_pass") == "new_house_2000plus":   return 1
        if (l.get("_search_pass") or "").startswith("pipe_reno_"): return 2
        return 3

    all_tram = confirmed + candidates
    all_tram.sort(key=lambda l: (_tier(l), -l["score"]))
    for rank, l in enumerate(all_tram, 1):
        l["rank"] = rank
    confirmed.sort(key=lambda l: -l["score"])
    candidates.sort(key=lambda l: -l["score"])
    tram_rented_out = [l for l in all_tram if l.get("is_rented_out")]

    print(f"\nTram — Confirmed: {len(confirmed)}  |  "
          f"Candidates: {len(candidates)}  |  Rented out: {len(tram_rented_out)}")

    # ── Uusimaa: pre-filter (no geo needed) → geocode survivors → score ──
    uu_pre: list[dict] = []
    for l in uu_to_check:
        if _effective_price(l) > UUSIMAA_PRICE_MAX:
            continue
        loan = l.get("housing_company_loan_eur")
        if loan is not None:
            dfp = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
            if dfp > 0 and float(loan) / dfp > UUSIMAA_LOAN_RATIO_MAX:
                continue
        year      = l.get("year_built") or 0
        pipe_done = _eval_pipe_done(l.get("pipe_renovation_info"), l.get("pipe_renovation_year"))
        if 1980 <= year <= 1995 and not pipe_done:
            continue
        uu_pre.append(l)
    print(f"\n  Pre-filter (price/loan/pipe): {len(uu_to_check)} → {len(uu_pre)} listings to geocode")

    print(f"  Geocoding {len(uu_pre)} PKS listings …")
    uu_fresh = 0
    uu_geocoded: list[dict] = []
    _PKS_GEO_FIELDS = ("lat", "lon", "nearest_hub", "hub_distance_m",
                       "nearest_mall", "mall_distance_m", "helsinki_central_km", "tram_badge")

    for listing in uu_pre:
        url  = listing.get("listing_url", "")
        addr = listing.get("address", "")
        city = listing.get("city", "")
        # Fast path: geo already stored in listing_cache from a prior run
        if url and url in cache and cache[url].get("lat") is not None:
            entry = cache[url]
            listing.update({k: entry[k] for k in _PKS_GEO_FIELDS if k in entry})
            uu_geocoded.append(listing)
            continue
        was_cached = f"{addr}, {city}, Finland" in geo_cache
        coords = geocode_address(addr, city, geo_cache)
        if not was_cached:
            uu_fresh += 1
            time.sleep(1.5)
        if coords is None:
            continue
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
        uu_geocoded.append(listing)

    _save_geo_cache(geo_cache)
    _save_cache(cache)  # persist geo fields written back during this run
    print(f"  {uu_fresh} fresh geocodes, {len(uu_pre)-uu_fresh} from cache")

    uu_passing: list[dict] = []
    for l in uu_geocoded:
        is_old = (l.get("year_built") or 9999) < 2000
        pipe_done = _eval_pipe_done(l.get("pipe_renovation_info"), l.get("pipe_renovation_year"))
        if not is_old:
            l["_search_pass"] = "new_house_2000plus"
        elif pipe_done:
            l["_search_pass"] = f"pipe_reno_{l.get('pipe_renovation_year') or 'done'}"
        else:
            l["_search_pass"] = "candidate_check_pipe_reno"
        l["monthly_cost_eur"] = round(monthly_cost_eur(l), 2)
        l["score"] = score_uusimaa_listing(l)
        uu_passing.append(l)

    uu_passing.sort(key=lambda l: -l["score"])
    for rank, l in enumerate(uu_passing, 1):
        l["rank"] = rank
    uusimaa_rented = [l for l in uu_passing if l.get("is_rented_out")]
    uusimaa_top5   = [l for l in uu_passing if not l.get("is_rented_out")][:UUSIMAA_TOP_UNRENTED]

    print(f"Uusimaa — Passing: {len(uu_passing)}  |  "
          f"Rented out: {len(uusimaa_rented)}  |  Watch list: {len(uusimaa_top5)}")

    # ── New build: geocode + score ────────────────────────────────────────
    nb_geo_cache = _load_geo_cache()
    nb_fresh = 0
    newbuild_pks: list[dict] = []
    print(f"\n  Geocoding {len(nb_to_check)} new build listings …")
    for listing in nb_to_check:
        url  = listing.get("listing_url", "")
        addr = listing.get("address", "")
        city = listing.get("city", "")
        if url and url in cache and cache[url].get("lat") is not None:
            entry = cache[url]
            listing.update({k: entry[k] for k in _PKS_GEO_FIELDS if k in entry})
        else:
            was_cached = f"{addr}, {city}, Finland" in nb_geo_cache
            coords = geocode_address(addr, city, nb_geo_cache)
            if not was_cached:
                nb_fresh += 1
                time.sleep(1.5)
            if coords is None:
                continue
            lat, lon = coords
            hub_name,  hub_dist  = nearest_hub(lat, lon)
            mall_name, mall_dist = nearest_mall(lat, lon)
            hc_km = haversine_m(lat, lon, HELSINKI_CENTRAL_COORDS[0], HELSINKI_CENTRAL_COORDS[1]) / 1000
            tram_name, tram_dist = nearest_tram_stop(lat, lon)
            tram_badge = {"stop": tram_name, "dist": round(tram_dist)} if tram_dist <= MAX_STOP_DIST_M else None
            geo_fields = {
                "lat": round(lat, 6), "lon": round(lon, 6),
                "nearest_hub": hub_name, "hub_distance_m": round(hub_dist),
                "nearest_mall": mall_name, "mall_distance_m": round(mall_dist),
                "helsinki_central_km": round(hc_km, 2), "tram_badge": tram_badge,
            }
            listing.update(geo_fields)
            if url and url in cache:
                cache[url].update(geo_fields)
        # loan filter
        loan = listing.get("housing_company_loan_eur")
        if loan is not None:
            dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
            if dfp > 0 and float(loan) / dfp > UUSIMAA_LOAN_RATIO_MAX:
                continue
        listing["_search_pass"] = "new_build"
        listing["monthly_cost_eur"] = round(monthly_cost_eur(listing), 2)
        listing["score"] = score_uusimaa_listing(listing)
        newbuild_pks.append(listing)

    _save_geo_cache(nb_geo_cache)
    _save_cache(cache)
    newbuild_pks.sort(key=lambda l: -l["score"])
    # Deduplicate: keep only the highest-scoring listing per street (same street =
    # same development project), then cap at NEWBUILD_TOP_N for a focused shortlist.
    _seen_bldg: set[str] = set()
    _deduped: list[dict] = []
    for l in newbuild_pks:
        addr = l.get("address", "")
        # Strip street number + apartment → street name only
        street = re.sub(r"\s+\d+.*$", "", addr.split(",")[0]).strip()
        key  = f"{street}|{l.get('city', '')}".lower()
        if key not in _seen_bldg:
            _seen_bldg.add(key)
            _deduped.append(l)
    newbuild_pks = _deduped[:NEWBUILD_TOP_N]
    for rank, l in enumerate(newbuild_pks, 1):
        l["rank"] = rank
    print(f"  {nb_fresh} fresh geocodes  |  New build passing: {len(_deduped)} unique buildings → top {len(newbuild_pks)}")

    # ── Results cache ────────────────────────────────────────────────────
    _save_results_cache(confirmed, candidates, tram_rented_out,
                        uusimaa_rented, uusimaa_top5, uu_passing, newbuild_pks)

    # ── Outputs ─────────────────────────────────────────────────────────
    all_tram_out = confirmed + candidates
    with open(_DATA / "results_tram.json", "w", encoding="utf-8") as fh:
        json.dump(all_tram_out, fh, ensure_ascii=False, indent=2)
    print(f"Saved → {_DATA / 'results_tram.json'}  ({len(all_tram_out)} listings)")

    with open(_DATA / "results_uusimaa.json", "w", encoding="utf-8") as fh:
        json.dump(uu_passing, fh, ensure_ascii=False, indent=2)
    print(f"Saved → {_DATA / 'results_uusimaa.json'}  ({len(uu_passing)} listings)")

    with open(_DATA / "results_newbuild.json", "w", encoding="utf-8") as fh:
        json.dump(newbuild_pks, fh, ensure_ascii=False, indent=2)
    print(f"Saved → {_DATA / 'results_newbuild.json'}  ({len(newbuild_pks)} listings)")

    generate_csv_report(confirmed, candidates, path=str(_DATA / "results_tram.csv"))
    generate_csv_report(uusimaa_rented, uusimaa_top5, path=str(_DATA / "results_uusimaa.csv"))
    generate_html_report(confirmed, candidates, tram_rented_out,
                         uusimaa_rented, uusimaa_top5, newbuild_pks)

    # ── Console summary ─────────────────────────────────────────────────
    w = 72
    print("\n" + "=" * w)
    print(f"{'TRAM INVESTMENT SUMMARY':^{w}}")
    print("=" * w)

    def show(l: dict, prefix: str = "") -> None:
        price = fmt_eur_console(l.get("price_eur"))
        dfp   = fmt_eur_console(l.get("debt_free_price_eur"))
        loan  = _loan_ratio_str(l)
        tag   = l.get("_search_pass", "")
        yr    = l.get("year_built", "?")
        note  = ("built " + str(yr) if "new" in tag
                 else f"pipe reno {l.get('pipe_renovation_year') or '✓'}"
                      if "reno" in tag and "cand" not in tag
                 else f"built {yr} — CHECK PIPE RENO")
        stop  = l.get("nearest_stop") or "?"
        dist  = f"{l.get('distance_m')} m" if l.get("distance_m") is not None else "? m"
        sc    = l.get("score", "?")
        rank  = l.get("rank", "?")
        mc    = l.get("monthly_cost_eur")
        hoito = l.get("hoitovastike_eur_month")
        tontti = l.get("tonttivuokra_eur_month")
        dfp_val = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
        mort  = monthly_mortgage(max(0.0, dfp_val - DOWN_PAYMENT_EUR))
        parts = [f"mortgage {mort:,.0f} €"]
        if hoito:  parts.append(f"hoito {hoito:,.0f} €")
        if tontti: parts.append(f"tontti {tontti:,.0f} €")
        mc_str = f"{mc:,.0f} €/mo  ({' + '.join(parts)})" if mc else "?"
        print(f"\n  #{rank} (score {sc}/125)  {prefix}{l.get('address', 'N/A')}")
        print(f"  {price}  (velaton {dfp})  |  loan {loan}  |  "
              f"{l.get('room_count','?')}h {l.get('size_sqm','?')}m²  |  {note}")
        print(f"  Monthly: {mc_str}")
        print(f"  Nearest stop: {stop} ({dist})  |  {l.get('district','')}, {l.get('city','')}")
        if l.get("listing_url"):
            print(f"  {l['listing_url']}")

    if confirmed:
        print("\n--- CONFIRMED ---")
        for l in confirmed: show(l)
    else:
        print("\n  No confirmed tram listings this run.")

    if candidates:
        print("\n--- CANDIDATES (verify pipe renovation) ---")
        for l in candidates: show(l, "[CHECK] ")
    else:
        print("  No tram candidates.")

    if tram_rented_out:
        print("\n--- RENTED OUT (immediate rental income) ---")
        for l in tram_rented_out: show(l, "[RENTED] ")
    else:
        print("\n  No tram rented-out listings found.")

    print(f"\n{'='*w}")
    print(f"{'UUSIMAA SUMMARY':^{w}}")
    print(f"{'='*w}")
    print(f"  Rented-out: {len(uusimaa_rented)}  |  Watch list (top {UUSIMAA_TOP_UNRENTED} unrented): {len(uusimaa_top5)}")
    for l in (uusimaa_rented + uusimaa_top5)[:8]:
        hub  = l.get("nearest_hub") or "?"
        hdm  = l.get("hub_distance_m") or "?"
        sc   = l.get("score", "?")
        tag  = "[RENTED] " if l.get("is_rented_out") else "[WATCH] "
        print(f"  {tag}#{l.get('rank')} ({sc}pts) {l.get('address','?')} — {hub} {hdm}m")
    print()


def fmt_eur_console(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f} €".replace(",", " ")
    except Exception:
        return str(v)


if __name__ == "__main__":
    main()
