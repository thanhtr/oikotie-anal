"""Investment scoring, mortgage/monthly-cost math, and loan-ratio helpers."""

from oikotie.config import (
    DOWN_PAYMENT_EUR, EURIBOR_12M, HELSINKI_CENTRAL_COORDS, LL_YIELD_FULL_PTS,
    LL_YIELD_ZERO_PTS,
    LOAN_MARGIN, LOAN_YEARS, PLANNED_TRANSIT, STOP_NOTE, STOP_TRANSFORMATION,
    RAIL_STATIONS, TRAM_STOP_PLANNED_MULT, TRAM_STOPS, TRANSPORT_HUBS,
)
from oikotie.geo import haversine_m, nearest_hub, nearest_mall
from oikotie.parsing import _eval_pipe_done


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
    score += STOP_TRANSFORMATION.get(stop, 5)

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


def _hub_pts(listing: dict, hubs=None) -> int:
    """Transport hub proximity (0–25 pts) — rail/metro drives tenant demand.
    Passing `hubs` recomputes from lat/lon against that list instead of
    trusting cached geo fields."""
    lat, lon = listing.get("lat"), listing.get("lon")
    hub_dist = None if hubs else listing.get("hub_distance_m")
    if hub_dist is None and lat is not None:
        _, hub_dist = nearest_hub(lat, lon, hubs or TRANSPORT_HUBS)
    if hub_dist is None:  return 0
    if hub_dist < 300:    return 25
    if hub_dist < 600:    return 20
    if hub_dist < 1000:   return 15
    if hub_dist < 1500:   return 10
    if hub_dist < 2500:   return 5
    return 0


def _centre_pts(listing: dict) -> int:
    """Helsinki Central proximity (0–15 pts) — distance-to-center is the #1 price driver."""
    lat, lon = listing.get("lat"), listing.get("lon")
    hc_km = listing.get("helsinki_central_km")
    if hc_km is None and lat is not None:
        hc_km = haversine_m(lat, lon, HELSINKI_CENTRAL_COORDS[0], HELSINKI_CENTRAL_COORDS[1]) / 1000
    if hc_km is None: return 0
    if hc_km < 2:     return 15
    if hc_km < 4:     return 12
    if hc_km < 7:     return 8
    if hc_km < 12:    return 4
    return 0


def _mall_pts(listing: dict, fresh: bool = False) -> int:
    """Nearest major mall / POI (0–10 pts) — services & walkability signal."""
    lat, lon = listing.get("lat"), listing.get("lon")
    mall_dist = None if fresh else listing.get("mall_distance_m")
    if mall_dist is None and lat is not None:
        _, mall_dist = nearest_mall(lat, lon)
    if mall_dist is None:  return 0
    if mall_dist < 500:    return 10
    if mall_dist < 1000:   return 8
    if mall_dist < 1500:   return 5
    if mall_dist < 2500:   return 2
    return 0


def _ppsqm_pts(listing: dict) -> int:
    """Debt-free price per m² (0–10 pts) — lower is better, PKS-scaled bands."""
    dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
    sqm = float(listing.get("size_sqm") or 0)
    if dfp <= 0 or sqm <= 0: return 0
    ppsqm = dfp / sqm
    if ppsqm < 2000: return 10
    if ppsqm < 3000: return 7
    if ppsqm < 4000: return 4
    if ppsqm < 5000: return 1
    return 0


def _ppsqm_pts_newbuild(listing: dict) -> int:
    """Debt-free €/m² for new builds (0–10 pts). New PKS stock sits at
    5 000–10 000 €/m², where the resale bands in _ppsqm_pts all score 0."""
    dfp = float(listing.get("debt_free_price_eur") or 0)
    sqm = float(listing.get("size_sqm") or 0)
    if dfp <= 0 or sqm <= 0: return 0
    ppsqm = dfp / sqm
    if ppsqm < 5000: return 10
    if ppsqm < 6000: return 8
    if ppsqm < 7000: return 6
    if ppsqm < 8000: return 4
    if ppsqm < 9000: return 2
    return 0


def planned_transit(listing: dict) -> tuple[int, dict | None]:
    """Planned-transit uplift (0–15 pts): best of PLANNED_TRANSIT and the Vantaan
    ratikka stops. Full points ≤ 500 m, half ≤ 1 km. Returns (pts, match)."""
    lat, lon = listing.get("lat"), listing.get("lon")
    if lat is None:
        return 0, None
    options = [(n, a, o, p, note, url) for n, a, o, p, note, url in PLANNED_TRANSIT]
    for name, slon, slat in TRAM_STOPS:
        options.append((f"Ratikka: {name}", slat, slon,
                        STOP_TRANSFORMATION.get(name, 5) * TRAM_STOP_PLANNED_MULT,
                        STOP_NOTE.get(name, "Vantaan ratikka stop, ops ~2029"),
                        "https://ratikka.vantaa.fi/en"))
    best_pts, best = 0, None
    for name, plat, plon, pts, note, url in options:
        d = haversine_m(lat, lon, plat, plon)
        got = pts if d <= 500 else pts // 2 if d <= 1000 else 0
        if got > best_pts:
            best_pts, best = got, {"name": name, "dist": round(d), "note": note, "url": url}
    return best_pts, best


def score_largeloan_listing(listing: dict) -> tuple[int, dict]:
    """Score 0–100 for large-loan new builds: appreciation/location potential
    plus after-tax cash yield. No building-quality or loan-ratio terms — all
    listings are new, and a high loan ratio is the point here.
    Returns (score, breakdown)."""
    transit_pts, transit = planned_transit(listing)
    cy = listing.get("cash_yield")
    span = LL_YIELD_FULL_PTS - LL_YIELD_ZERO_PTS
    yield_pts = 0 if cy is None else round(25 * min(max((cy - LL_YIELD_ZERO_PTS) / span, 0.0), 1.0))
    parts = {
        "hub":     _hub_pts(listing, hubs=RAIL_STATIONS),
        "centre":  _centre_pts(listing),
        "mall":    _mall_pts(listing, fresh=True),
        "transit": transit_pts,
        "yield":   yield_pts,
        "ppsqm":   _ppsqm_pts_newbuild(listing),
    }
    return sum(parts.values()), {"parts": parts, "transit": transit}


def score_uusimaa_listing(listing: dict) -> int:
    """Score 0–100 for Uusimaa non-tram listings. Higher = better investment candidate.

    Factors: transport hub proximity (25), Helsinki Central distance (15),
    nearest mall (10), building quality (30), price/m² (10), loan ratio (5),
    monthly non-mortgage costs (5).
    """
    score = 0

    score += _hub_pts(listing) + _centre_pts(listing) + _mall_pts(listing)

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
    score += _ppsqm_pts(listing)
    dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)

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


def _effective_price(listing: dict) -> float:
    return float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 999_999)


def _loan_acceptable(listing: dict, loan_ratio_max: float) -> bool:
    loan = listing.get("housing_company_loan_eur")
    if loan is None:
        return True   # unknown — treat as acceptable (already checked individually)
    loan = float(loan)
    if loan == 0:
        return True
    dfp = float(listing.get("debt_free_price_eur") or listing.get("price_eur") or 0)
    return dfp > 0 and (loan / dfp) <= loan_ratio_max


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
