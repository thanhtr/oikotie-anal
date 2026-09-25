"""Text extraction: search-card parsing, individual-listing-page parsing,
and the Finnish-language pipe-renovation / rental-status regex heuristics."""

import re
import sys
from datetime import datetime
from typing import Optional

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
_BOOK_YES_TERM = re.compile(r"(tuloute\w*|tuloutus\w*|tulouttaa|tuloutettu\w*)", re.IGNORECASE)
_BOOK_NO_TERM  = re.compile(r"(rahastoi\w*|rahastointi\w*)", re.IGNORECASE)
_GRACE_TERM    = re.compile(r"(lyhennysvapaa\w*|lyhennykset\s+alka\w*|lyhentäminen\s+alkaa)", re.IGNORECASE)
_FIN_NUMWORDS  = {"ensimmäinen": 1, "yksi": 1, "yhden": 1, "kaksi": 2, "kahden": 2, "kolme": 3,
                  "kolmen": 3, "neljä": 4, "neljän": 4, "viisi": 5, "viiden": 5}
_EUR_KK = r"([\d\xa0\s]+(?:[,.]\d+)?)\s*[\xa0\s]*€\s*/\s*kk"

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


def _snippet(text: str, m: re.Match, pad: int = 150) -> str:
    return text[max(0, m.start() - pad):min(len(text), m.end() + pad)].strip()


def parse_largeloan_fields(text: str) -> dict:
    """Financing-charge, grace-period and booking-method fields for the
    large-loan category. Oikotie shows two charge blocks for new builds:
    "Vastikkeet lyhennysvapaakaudella" (interest only) and
    "Vastikkeet lyhennysvapaan jälkeen" (interest + principal)."""
    result: dict = {}

    def charge(label: str, chunk: str):
        m = re.search(label + r"\s*\n+" + _EUR_KK, chunk)
        return _parse_fin_num(m.group(1)) if m else None

    after_i = text.find("Vastikkeet lyhennysvapaan jälkeen")
    during_i = text.find("Vastikkeet lyhennysvapaakaudella")
    if after_i >= 0:
        after = text[after_i:after_i + 400]
        during = text[during_i:after_i] if 0 <= during_i < after_i else ""
        fin_after = charge("(?:Pääomavastike|Rahoitusvastike)", after)
        fin_during = charge("(?:Pääomavastike|Rahoitusvastike)", during) if during else None
    else:
        # Single block: "Rahoitusvastike\n123 € / kk" — the label must end the line so
        # "Rahoitusvastike, putkiremontti …" breakdown lines don't match.
        fin_after = charge("(?:Pääomavastike|Rahoitusvastike)", text)
        fin_during = None
        if fin_after is None:
            total = charge("Yhtiövastike yhteensä", text)
            hoito = charge("Hoitovastike", text)
            if total is not None and hoito is not None and total > hoito:
                fin_after = round(total - hoito, 2)
    result["rahoitusvastike_eur_month"] = fin_after if fin_after is not None else 0.0
    result["rahoitusvastike_grace_eur_month"] = fin_during

    # Completion estimate: "Lisätietoa vapautumisesta\nArviolta 12/2027"
    m = re.search(r"vapautumisesta\s*\n+[^\n]*?(?:(\d{1,2})\s*/\s*)?(20\d\d)", text)
    result["completion_year"] = int(m.group(2)) if m else None

    # Grace period: explicit year, else "N (asumis)vuotta/vuosi" from completion
    grace_end = None
    grace_info = None
    gm = _GRACE_TERM.search(text)
    if gm:
        grace_info = _snippet(text, gm)
        ym = re.search(r"\b(20[2-4]\d)\b", grace_info)
        if ym:
            grace_end = int(ym.group(1))
        else:
            nm = re.search(r"\b(\d|" + "|".join(_FIN_NUMWORDS) + r")\s+(?:ensimmäistä\s+)?(?:asumis)?vuo(?:tta|si|den)",
                           grace_info, re.IGNORECASE)
            base = result["completion_year"] or datetime.now().year
            if nm:
                w = nm.group(1).lower()
                grace_end = base + (int(w) if w.isdigit() else _FIN_NUMWORDS[w])
    result["grace_period_info"] = grace_info
    result["grace_end_year"] = grace_end

    # Booking method (tuloutus vs rahastointi) — text hint only
    yes_m, no_m = _BOOK_YES_TERM.search(text), _BOOK_NO_TERM.search(text)
    if yes_m and not no_m:
        result["booking_method"], result["booking_info"] = "yes", _snippet(text, yes_m)
    elif no_m and not yes_m:
        result["booking_method"], result["booking_info"] = "no", _snippet(text, no_m)
    else:
        result["booking_method"] = "unknown"
        result["booking_info"] = " … ".join(_snippet(text, m) for m in (yes_m, no_m) if m) or None

    m = re.search(r"Uudiskohde\s*\n+\s*Kyllä", text)
    result["is_new_development"] = bool(m)
    return result


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


def fetch_listing_details(page, url: str, cache: dict, require_key: str = "hoitovastike_eur_month") -> dict:
    """Load individual listing page; return loan + pipe reno + rental details.

    `require_key` decides cache freshness: an entry missing that key is
    re-fetched (the large-loan pool passes "rahoitusvastike_eur_month")."""
    if url in cache and "hoitovastike_eur_month" in cache[url] and require_key in cache[url]:
        return cache[url]

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector("h1", timeout=15000)
        except Exception:
            pass
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

    # Rental income — parse €/kk from rented_out_info snippet
    result["rental_income_eur_month"] = None
    if result.get("rented_out_info"):
        m = re.search(r"([\d\xa0\s]+)\s*€\s*/\s*kk", result["rented_out_info"])
        if m:
            result["rental_income_eur_month"] = _parse_fin_num(m.group(1))

    result.update(parse_largeloan_fields(text))

    # Keep geo fields from an older entry so re-fetches don't force a re-geocode
    old = cache.get(url) or {}
    for k, v in old.items():
        result.setdefault(k, v)
    cache[url] = result
    return result
