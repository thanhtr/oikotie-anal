"""Rough monthly rent estimate: the listing's own stated rent, else a district
median from rented-out listings seen this run, else the Statistics Finland
city × room-count €/m² table in config."""

from statistics import median

from oikotie.config import RENT_DISTRICT_MIN_SAMPLES, RENT_EUR_SQM_CITY

_SANE_EUR_SQM = (10.0, 40.0)   # drop parse junk (e.g. a hoitovastike picked up as rent)


def _district_key(l: dict) -> str:
    return f"{(l.get('district') or '').strip()}|{(l.get('city') or '').strip()}".lower()


def build_rent_model(listings: list[dict]) -> dict[str, list[float]]:
    """District → list of listed €/m² rents, from any listing with a stated rent."""
    model: dict[str, list[float]] = {}
    seen: set[str] = set()
    for l in listings:
        url = l.get("listing_url")
        rent, sqm = l.get("rental_income_eur_month"), l.get("size_sqm")
        if not rent or not sqm or url in seen:
            continue
        seen.add(url)
        per_sqm = float(rent) / float(sqm)
        if _SANE_EUR_SQM[0] <= per_sqm <= _SANE_EUR_SQM[1]:
            model.setdefault(_district_key(l), []).append(per_sqm)
    return model


def estimate_rent(l: dict, model: dict[str, list[float]]) -> tuple[float | None, str]:
    """Return (rent €/month, source label)."""
    sqm = float(l.get("size_sqm") or 0)
    listed = l.get("rental_income_eur_month")
    if listed and (sqm <= 0 or _SANE_EUR_SQM[0] <= float(listed) / sqm <= _SANE_EUR_SQM[1]):
        return float(listed), "listed"
    if sqm <= 0:
        return None, "no size"
    samples = model.get(_district_key(l), [])
    if len(samples) >= RENT_DISTRICT_MIN_SAMPLES:
        return round(median(samples) * sqm), f"district median n={len(samples)}"
    city_tbl = RENT_EUR_SQM_CITY.get((l.get("city") or "").strip().lower())
    if not city_tbl:
        return None, "no city data"
    rooms = min(max(int(l.get("room_count") or (1 if sqm < 35 else 2)), 1), 3)
    return round(city_tbl[rooms] * sqm), f"city avg {rooms if rooms < 3 else '3+'}h"
