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


def fetch_listing_details(page, url: str, cache: dict) -> dict:
    """Load individual listing page; return loan + pipe reno + rental details."""
    if url in cache and "hoitovastike_eur_month" in cache[url]:
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

    cache[url] = result
    return result
