"""Constants: search locations, thresholds, mortgage model, stop metadata."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_FILE          = DATA_DIR / "listing_cache.json"
GEO_CACHE_FILE      = DATA_DIR / "geocode_cache.json"
RESULTS_CACHE_FILE  = DATA_DIR / "results_cache.json"
RESULTS_CACHE_TTL_HOURS = 12  # use --force to bypass after changing filter constants

BASE_URL = "https://asunnot.oikotie.fi"

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
    ("Malmi",             60.2508, 25.0112),
    ("Myyrmäki",          60.2612, 24.8545),
]

# Metro + commuter-rail stations in Helsinki/Espoo/Vantaa/Kauniainen — OpenStreetMap
# railway=station (light-rail stops excluded), fetched 2026-09-25. (name, lat, lon).
# Used by the large-loan score; the Uusimaa score keeps TRANSPORT_HUBS so its
# cached hub distances stay comparable.
RAIL_STATIONS: list[tuple[str, float, float]] = [
    ("Aalto-yliopisto metro", 60.1845, 24.8236),
    ("Aviapolis", 60.3045, 24.9567),
    ("Espoo", 60.2051, 24.6561),
    ("Espoonlahti metro", 60.1494, 24.6547),
    ("Finnoo metro", 60.153, 24.7119),
    ("Hakaniemi metro", 60.1805, 24.9502),
    ("Helsingin yliopisto metro", 60.1728, 24.9486),
    ("Helsinki", 60.1721, 24.9412),
    ("Herttoniemi metro", 60.1946, 25.0302),
    ("Hiekkaharju", 60.3035, 25.0496),
    ("Huopalahti", 60.2183, 24.8935),
    ("Ilmala", 60.2077, 24.9213),
    ("Itäkeskus metro", 60.21, 25.0774),
    ("Kaitaa metro", 60.1496, 24.6908),
    ("Kalasatama metro", 60.1875, 24.9769),
    ("Kamppi metro", 60.169, 24.9317),
    ("Kannelmäki", 60.2397, 24.8766),
    ("Kauklahti", 60.1894, 24.6004),
    ("Kauniainen", 60.2118, 24.7296),
    ("Keilaniemi metro", 60.1756, 24.8295),
    ("Kera", 60.2166, 24.7557),
    ("Kilo", 60.2179, 24.7824),
    ("Kivenlahti metro", 60.1555, 24.6363),
    ("Kivistö", 60.3147, 24.8473),
    ("Koivuhovi", 60.207, 24.7023),
    ("Koivukylä", 60.3236, 25.0604),
    ("Koivusaari metro", 60.1636, 24.8538),
    ("Kontula metro", 60.236, 25.0836),
    ("Korso", 60.3515, 25.0788),
    ("Kulosaari metro", 60.1888, 25.0081),
    ("Käpylä", 60.2202, 24.9461),
    ("Lauttasaari metro", 60.1595, 24.8787),
    ("Leinelä", 60.3225, 25.04),
    ("Lentoasema", 60.3158, 24.9686),
    ("Leppävaara", 60.2194, 24.8135),
    ("Louhela", 60.2709, 24.8534),
    ("Malmi", 60.2509, 25.0108),
    ("Malminkartano", 60.2494, 24.8612),
    ("Martinlaakso", 60.2781, 24.8528),
    ("Matinkylä metro", 60.1597, 24.7391),
    ("Mellunmäki metro", 60.2392, 25.1112),
    ("Myllypuro metro", 60.225, 25.0757),
    ("Myyrmäki", 60.2612, 24.8548),
    ("Mäkkylä", 60.2212, 24.8431),
    ("Niittykumpu metro", 60.1704, 24.763),
    ("Oulunkylä", 60.2281, 24.9665),
    ("Pasila", 60.1987, 24.9334),
    ("Pitäjänmäki", 60.2234, 24.8596),
    ("Pohjois-Haaga", 60.2304, 24.8835),
    ("Puistola", 60.2756, 25.0366),
    ("Pukinmäki", 60.2422, 24.9938),
    ("Puotila metro", 60.2147, 25.0931),
    ("Rastila metro", 60.2054, 25.1216),
    ("Rautatientori metro", 60.1704, 24.9398),
    ("Rekola", 60.3323, 25.0683),
    ("Ruoholahti metro", 60.1632, 24.9156),
    ("Siilitie metro", 60.2053, 25.044),
    ("Soukka metro", 60.1415, 24.6699),
    ("Sörnäinen metro", 60.1866, 24.9591),
    ("Tapanila", 60.2625, 25.0286),
    ("Tapiola metro", 60.175, 24.8038),
    ("Tikkurila", 60.2928, 25.0446),
    ("Tuomarila", 60.206, 24.6818),
    ("Urheilupuisto metro", 60.1746, 24.7811),
    ("Valimo", 60.222, 24.8758),
    ("Vantaankoski", 60.2859, 24.8481),
    ("Vehkala", 60.2953, 24.8438),
    ("Vuosaari metro", 60.2072, 25.1425),
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
    ("Malmi",     60.2510, 25.0100),
    ("Myyrmanni", 60.2610, 24.8540),
]

HELSINKI_CENTRAL_COORDS: tuple[float, float] = (60.1698, 24.9382)

# ---------------------------------------------------------------------------
# Large-loan new build (replaces the old "PKS Uutuudet" view)
# Flats where a big housing-company loan + tuloutus booking lets the landlord
# deduct the whole rahoitusvastike (principal included) from rental income.
# ---------------------------------------------------------------------------
LL_SEARCH_VELATON_MAX = 600_000  # price[max] on the search URL (bounds scrape size); None = no cap
LL_MYYNTI_MAX         = 200_000  # cash price (myyntihinta) cap — the real filter
LL_MIN_LOAN_RATIO     = 0.50     # lainaosuus / velaton hinta
LL_MAX_AGE_YEARS      = 5        # year_built >= now − 5 (future completion years pass)
LL_MIN_PRINCIPAL_PCT  = 0.015    # principal_est / loan_share per year to count as real amortisation
LL_HOLD_YEARS         = 10       # holding horizon: grace-period gate + lifetime estimate
LL_TOP_N              = 50
# After-tax cash yield → 0–25 pts, linear between these. Big-loan flats are often
# cash-negative (rent pays the principal too), so the floor sits below zero.
LL_YIELD_ZERO_PTS     = -0.05
LL_YIELD_FULL_PTS     = 0.05

TAX_RATE          = 0.30   # capital income tax; 0.34 above 30 000 €/yr
CO_LOAN_RATE      = 0.04   # assumed housing-company loan interest rate
APPRECIATION_RATE = 0.01   # yearly price growth, lifetime estimate only
LL_REINVEST_RATE  = 0.04   # return on tax saved early (timing value of the deduction)
DEDUCTION_ENABLED = True   # principal deduction via tuloutus — flip off if legislated away

# Free-market rent €/m²/mo for new tenancies, by city and room count (1, 2, 3+).
# Statistics Finland table asvu/15fa, 2026Q2 (published 2026-07-16). Update quarterly.
RENT_EUR_SQM_CITY: dict[str, dict[int, float]] = {
    "helsinki": {1: 26.71, 2: 21.19, 3: 20.26},
    "espoo":    {1: 23.53, 2: 18.73, 3: 17.67},
    "vantaa":   {1: 22.61, 2: 16.96, 3: 15.40},
}
RENT_DISTRICT_MIN_SAMPLES = 3   # listed rents needed before a district median overrides the city table

# Planned (not yet operating) rail/tram lines that should lift nearby prices.
# (name, lat, lon, pts 0–15, note, source_url). Full pts ≤ 500 m, half ≤ 1 km.
# Vantaan ratikka stops are added from TRAM_STOPS × STOP_TRANSFORMATION in scoring.
PLANNED_TRANSIT: list[tuple[str, float, float, int, str, str]] = [
    ("Viima: Malmi",          60.2508, 25.0112, 12, "Viikki–Malmi light rail, ops early 2030s",
     "https://infraohjelmahelsinki.fi/en/viikki-malmi-light-rail/"),
    ("Viima: Malmi airfield", 60.2540, 25.0420, 15, "Viikki–Malmi light rail + new Malmi airfield district",
     "https://infraohjelmahelsinki.fi/en/viikki-malmi-light-rail/"),
    ("Viima: Latokartano",    60.2325, 25.0390, 12, "Viikki–Malmi light rail, ops early 2030s",
     "https://infraohjelmahelsinki.fi/en/viikki-malmi-light-rail/"),
    ("Viima: Viikki",         60.2260, 25.0150, 10, "Viikki–Malmi light rail, ops early 2030s",
     "https://infraohjelmahelsinki.fi/en/viikki-malmi-light-rail/"),
    ("Kruunusillat: Kruunuvuorenranta", 60.1760, 25.0040, 12, "Crown Bridges tram to centre, opens ~2027",
     "https://www.kruunusillat.fi/en"),
    ("Kruunusillat: Yliskylä",          60.1725, 25.0520, 12, "Crown Bridges tram to centre, opens ~2027",
     "https://www.kruunusillat.fi/en"),
]
TRAM_STOP_PLANNED_MULT = 3    # Vantaan ratikka: STOP_TRANSFORMATION (0–5) × 3 → 0–15 pts

MAX_DETAIL_CHECKS = 9999    # effectively unlimited

# ---------------------------------------------------------------------------
# Scrape sanity floors — a raw listing count below these means a search
# request almost certainly got rate-limited/blocked and returned an empty
# results page, not that the market genuinely has that few listings. Set
# well below normal volume (typically 300+/2000+/1800+) purely to catch a
# total-failure case; see cli.py::_check_scrape_sanity.
# ---------------------------------------------------------------------------
MIN_TRAM_RAW      = 50
MIN_UUSIMAA_RAW   = 200
MIN_LARGELOAN_RAW = 200

# Tram transformation score per stop (0–5 pts).
# 0 = already a major transit hub — tram adds negligible marginal value, prices priced-in.
# 2 = within an existing hub's catchment — already benefiting from existing transit.
# 5 = bus-only today; tram will meaningfully transform the neighbourhood.
# Sources: Vantaa city kaavarunko plans, WSP research, Sp-Koti Feb 2025, YLE reporting.
STOP_TRANSFORMATION: dict[str, int] = {
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
STOP_NOTE: dict[str, str] = {
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
STOP_LINKS: dict[str, list[tuple[str, str]]] = {
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

# ---------------------------------------------------------------------------
# Market & project risk factors shown in the collapsible "risks" panel.
# Each dict: severity ("opp" | "high" | "med"), text, url, label.
# ---------------------------------------------------------------------------
TRAM_MARKET_RISKS: list[dict] = [
    {
        "severity": "high",
        "sev_label": "HIGH",
        "text": "Vantaa apartment prices have been the worst-performing major city 2024–2025 (–9.1% peak YoY, –5.2% May 2025)",
        "url": "https://www.helsinkitimes.fi/finland/finland-news/domestic/27245-housing-prices-drop-again-in-may-with-vantaa-hit-hardest.html",
        "label": "helsinkitimes",
    },
    {
        "severity": "high",
        "sev_label": "HIGH",
        "text": "Rental vacancy in HMA tripled 2020–2024; Vantaa occupancy declined Q4 2025 while Helsinki/Espoo held steady",
        "url": "https://innagroup.fi/en/news/market-reviews/residential-rental-market-q4-2025-seasonal-fluctuations-and-economic-conditions-reflected-in-q4-outlook-for-2026-cautiously-upward/",
        "label": "INNA Q4 2025",
    },
    {
        "severity": "high",
        "sev_label": "HIGH",
        "text": "Tram budget already overrun 16%+ (€647M → €750M) before construction started; Vantaa in €79.7M fiscal deficit with €544M tram commitment",
        "url": "https://www.mtvuutiset.fi/artikkeli/vantaan-ratikan-hinta-noussut-750-miljoonaan-selvasti-muita-kaupunkeja-kalliimpi/9246426",
        "label": "MTV Uutiset",
    },
    {
        "severity": "high",
        "sev_label": "HIGH",
        "text": "New-build oversupply: YIT had 1,359 completed unsold units (full year inventory) in 2024; developers offering concessions, competing directly with private investors",
        "url": "https://www.salkunrakentaja.fi/2024/05/yit-myymattomat-asunnot/",
        "label": "salkunrakentaja",
    },
    {
        "severity": "med",
        "sev_label": "MED",
        "text": "Tram opens at earliest 2029 — asking prices already reflect \"tram premium\" but buyers bear 3+ years of financing with no transit benefit",
        "url": "https://ratikka.vantaa.fi/en/traffic-and-transport/vantaa-light-rail/information-about-vantaa-light-rail",
        "label": "ratikka.vantaa.fi",
    },
    {
        "severity": "med",
        "sev_label": "MED",
        "text": "Finnish construction sector: 381 bankruptcies in Jan 2025 alone — risk of developer insolvency on pre-completion new builds",
        "url": "https://www.rakennuslehti.fi/2025/02/konkurssiin-haettiin-tammikuussa-kymmenia-rakennusalan-yrityksia/",
        "label": "rakennuslehti",
    },
]

UUSIMAA_MARKET_RISKS: list[dict] = [
    {
        "severity": "opp",
        "sev_label": "OPP",
        "text": "Occupancy recovering — Helsinki metro rental occupancy 94% in Q3 2025, best since H1 2020; oversupply gradually melting away",
        "url": "https://rettamanagement.fi/en/ajankohtaista/releases/finnish-residential-rental-market-q3-2025-strong-results-as-expected/",
        "label": "Retta Q3 2025",
    },
    {
        "severity": "opp",
        "sev_label": "OPP",
        "text": "Gross yields 5–7% in transit-connected PKS suburbs; HMA identified as clear growth area 2025–2026; new construction halted → supply constraint building",
        "url": "https://investropa.com/blogs/news/helsinki-rental-yields",
        "label": "Investropa 2026",
    },
    {
        "severity": "opp",
        "sev_label": "OPP",
        "text": "Prices near historical lows — buyers market; sellers negotiating; current correction may prove excellent entry if bought below replacement cost",
        "url": "https://kasvutalous.fi/%F0%9F%8F%A0-asuntomarkkinoiden-toipuminen-suomessa-mita-tapahtuu-vuonna-2026/",
        "label": "kasvutalous.fi",
    },
    {
        "severity": "med",
        "sev_label": "RISK",
        "text": "Rental supply still abundant — non-subsidized rents declined –1.3% recently; upward rent pressure will take more time to materialize",
        "url": "https://rettamanagement.fi/en/ajankohtaista/releases/finnish-residential-rental-market-q3-2025-strong-results-as-expected/",
        "label": "Retta Management",
    },
    {
        "severity": "med",
        "sev_label": "RISK",
        "text": "Price uncertainty — realistic planning range for Helsinki next 12 months: –3% to +2%; small further dip in early 2026 remains plausible",
        "url": "https://investropa.com/blogs/news/helsinki-good-time",
        "label": "Investropa 2026",
    },
    {
        "severity": "high",
        "sev_label": "RISK",
        "text": "Pipe renovation liability in 1975–1995 Helsinki/Espoo/Vantaa stock — major capital expenditure risk; confirm renovation status before any offer",
        "url": "https://www.kiinteistoliitto.fi/",
        "label": "kiinteistöliitto",
    },
    {
        "severity": "med",
        "sev_label": "RISK",
        "text": "Interest rate sensitivity — Euribor 12M at 2.2–2.3%; any reversal upward directly compresses net yield on leveraged properties",
        "url": "https://www.sijoittaja.fi/424295/asuntosijoittaminen-vuonna-2026/",
        "label": "sijoittaja.fi",
    },
]
