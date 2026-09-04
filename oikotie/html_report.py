"""Renders the generated static report (index.html) via Jinja2 templates.

Builds a plain-data render context per listing/table-row/section so the
templates carry no business logic — `mode` ("tram" | "uusimaa") only affects
which optional fields get populated (stop-note vs hub/mall lines, tram-stop
vs tram-badge), so a single card/table-row template serves both views.
"""

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from oikotie.config import (
    DATA_DIR, DOWN_PAYMENT_EUR, LOAN_RATIO_MAX, MAX_STOP_DIST_M, PRICE_MAX,
    STOP_LINKS, STOP_NOTE, TRAM_MARKET_RISKS, UUSIMAA_LOAN_RATIO_MAX,
    UUSIMAA_MARKET_RISKS, UUSIMAA_PRICE_MAX, UUSIMAA_TOP_UNRENTED,
)
from oikotie.pipelines import listing_red_flags, listing_red_flags_uusimaa
from oikotie.scoring import _loan_ratio_str, monthly_mortgage

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def fmt_eur(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f} €".replace(",", " ")
    except Exception:
        return str(v)


def _get_env() -> Environment:
    return Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


def _status_badge(l: dict) -> dict:
    tag = l.get("_search_pass", "")
    if tag == "new_house_2000plus":
        return {"cls": "new", "text": f"built {l.get('year_built', '')}"}
    if tag == "candidate_check_pipe_reno":
        return {"cls": "cand", "text": f"built {l.get('year_built', '')} · verify pipe"}
    reno_yr = l.get("pipe_renovation_year")
    label = f"pipe reno {reno_yr}" if reno_yr else "pipe reno ✓"
    return {"cls": "reno", "text": label}


def _card_context(l: dict, mode: str) -> dict:
    """Build the render context for one listing card. `mode` is "tram" or
    "uusimaa" — it only decides which optional fields get populated."""
    url = l.get("listing_url") or ""
    parts = [p for p in [l.get("address", "N/A"), l.get("district") or "", l.get("city") or ""] if p]
    full_addr = ", ".join(parts)

    rank, sc = l.get("rank", ""), l.get("score", "")
    rank_s = f"#{rank} · {sc} pts" if rank else ""

    dfp_v = float(l.get("debt_free_price_eur") or l.get("price_eur") or 0)
    price_s = fmt_eur(dfp_v)

    loan = l.get("housing_company_loan_eur")
    if loan is not None:
        loan_f = float(loan)
        pct = f" ({loan_f/dfp_v*100:.0f}%)" if dfp_v > 0 and loan_f > 0 else ""
        loan_s = "0 € yhtiölaina" if loan_f == 0 else f"+{fmt_eur(loan_f)} yhtiölaina{pct}"
    else:
        loan_s = "yhtiölaina ?"

    hoito  = l.get("hoitovastike_eur_month")
    tontti = l.get("tonttivuokra_eur_month")
    monthly_str = None
    if dfp_v > 0:
        mort_v = monthly_mortgage(max(0.0, dfp_v - DOWN_PAYMENT_EUR))
        total_fixed = mort_v + (float(hoito) if hoito else 0) + (float(tontti) if tontti else 0)
        monthly_str = f"{total_fixed:,.0f} €/mo est.".replace(",", " ")

    rental_inc = l.get("rental_income_eur_month")
    yield_str = None
    if rental_inc and dfp_v > 0:
        gross_yield = float(rental_inc) * 12 / dfp_v * 100
        yield_str = f"{gross_yield:.1f}% gross yield · {fmt_eur(rental_inc)}/mo rent"

    meta_parts = []
    if l.get("room_count"): meta_parts.append(f"{l['room_count']}h")
    if l.get("size_sqm"):   meta_parts.append(f"{l['size_sqm']} m²")
    if l.get("floor"):      meta_parts.append(f"fl {l['floor']}")
    if l.get("year_built"): meta_parts.append(str(l["year_built"]))
    meta_s = " · ".join(meta_parts)

    badges = [_status_badge(l)]
    if mode == "tram":
        stop = l.get("nearest_stop") or ""
        dist_m = l.get("distance_m")
        if stop:
            badges.append({"cls": "tram", "text": f"🚋 {stop} {round(dist_m) if dist_m is not None else '?'}m"})
    else:
        tb = l.get("tram_badge")
        if tb:
            badges.append({"cls": "tram", "text": f"🚋 {tb['stop']} {tb['dist']}m"})
    if l.get("is_rented_out"):
        badges.append({"cls": "rent", "text": "rented out"})

    note = None
    hub_line = mall_line = None
    if mode == "tram":
        stop = l.get("nearest_stop") or ""
        stop_note = STOP_NOTE.get(stop, "")
        if stop_note:
            note = {"text": stop_note,
                    "links": [{"url": u, "label": lb} for u, lb in STOP_LINKS.get(stop, [])]}
        flags = listing_red_flags(l)
    else:
        hub, hdist = l.get("nearest_hub") or "?", l.get("hub_distance_m")
        hc_km = l.get("helsinki_central_km")
        hub_line = f"🚉 {hub} · {round(hdist) if hdist is not None else '?'}m"
        if hc_km:
            hub_line += f"  ·  🏙 {hc_km:.1f} km centre"
        mall, mdist = l.get("nearest_mall") or "?", l.get("mall_distance_m")
        if mdist is not None:
            mall_line = f"🛍 {mall} · {round(mdist)}m"
        flags = listing_red_flags_uusimaa(l)

    return {
        "url": url, "full_addr": full_addr, "rank_s": rank_s, "price_s": price_s,
        "loan_s": loan_s, "monthly_str": monthly_str, "yield_str": yield_str,
        "meta_s": meta_s, "badges": badges, "note": note,
        "hub_line": hub_line, "mall_line": mall_line,
        "flags": [{"text": t, "url": u, "label": lb} for t, u, lb in flags],
        "reno": l.get("pipe_renovation_info") or "",
    }


def _table_row_context(l: dict, mode: str, row_class: str = "") -> dict:
    dfp = l.get("debt_free_price_eur") or l.get("price_eur") or 0
    rank = l.get("rank", "")
    sc   = l.get("score", "")
    rank_s = f"#{rank} · {sc}" if (rank is not None and rank != "") else "—"
    ctx = {
        "row_class": row_class,
        "rank_s": rank_s,
        "url": l.get("listing_url") or "",
        "addr": l.get("address", "—"),
        "district": l.get("district") or "—",
        "dfp_s": fmt_eur(dfp),
        "loan_s": _loan_ratio_str(l),
        "rooms": l.get("room_count", "—"),
        "sqm": l.get("size_sqm", "—"),
        "year": l.get("year_built", "—"),
    }
    if mode == "tram":
        tag = l.get("_search_pass", "")
        ctx["status"] = ("new ≥2000" if tag == "new_house_2000plus"
                         else "check pipe reno" if tag == "candidate_check_pipe_reno"
                         else "pipe reno ✓")
    else:
        hub, hdist = l.get("nearest_hub") or "—", l.get("hub_distance_m")
        ctx["hub_str"] = f"{hub} {round(hdist)}m" if hdist is not None else hub
        ctx["score"] = l.get("score", "—")
    return ctx


def _section(title: str, note: str, listings: list[dict], cls: str, mode: str) -> dict | None:
    if not listings:
        return None
    return {
        "title": title, "note": note, "cls": cls, "count": len(listings),
        "cards": [_card_context(l, mode) for l in listings],
    }


def generate_html_report(confirmed: list[dict], candidates: list[dict],
                         rented_out: list[dict] = None,
                         uusimaa_rented: list[dict] = None,
                         uusimaa_top5: list[dict] = None,
                         newbuild_pks: list[dict] = None,
                         path=None) -> None:
    if path is None:
        path = DATA_DIR / "index.html"
    rented_out     = rented_out     or []
    uusimaa_rented = uusimaa_rented or []
    uusimaa_top5   = uusimaa_top5   or []
    newbuild_pks   = newbuild_pks   or []

    # ── Tram display tiers — rented excluded from other sections to avoid duplication
    new_cards  = [l for l in confirmed  if l.get("_search_pass") == "new_house_2000plus"
                  and not l.get("is_rented_out")]
    pipe_cards = [l for l in confirmed  if (l.get("_search_pass") or "").startswith("pipe_reno_")
                  and not l.get("is_rented_out")]
    cand_cards = [l for l in candidates if not l.get("is_rented_out")]

    tram_sections = [s for s in [
        _section("Rented Out — immediate rental income",
                 "Currently tenanted. Rental income offsets costs from day one.",
                 rented_out, "sec-rented", "tram"),
        _section("New Builds (≥ 2000)",
                 "Built 2000 or later — no pipe renovation concern.",
                 new_cards, "sec-new", "tram"),
        _section("Older Builds — Pipe Renovation Done",
                 "Pre-2000 buildings with confirmed completed pipe renovation.",
                 pipe_cards, "sec-reno", "tram"),
        _section("Candidates — Pipe Renovation Unverified",
                 "Older buildings where pipe renovation status could not be confirmed "
                 "automatically. Verify manually before deciding.",
                 cand_cards, "sec-cand", "tram"),
    ] if s]

    tram_table_rows = (
        [_table_row_context(l, "tram", "row-rented") for l in rented_out] +
        [_table_row_context(l, "tram", "row-confirmed") for l in confirmed
         if not l.get("is_rented_out")] +
        [_table_row_context(l, "tram", "row-cand") for l in candidates
         if not l.get("is_rented_out")]
    )

    uu_sections = [s for s in [
        _section("Rented Out — Helsinki / Espoo / Vantaa",
                 "For-sale apartments with an existing tenant. Immediate rental income from day one.",
                 uusimaa_rented, "sec-rented", "uusimaa"),
        _section(f"Watch List — Top {UUSIMAA_TOP_UNRENTED} Unrented",
                 "Highest-scoring unrented apartments in Helsinki/Espoo/Vantaa by hub-proximity "
                 "model. Verify pipe reno and local market before deciding.",
                 uusimaa_top5, "sec-new", "uusimaa"),
    ] if s]

    uu_table_rows = (
        [_table_row_context(l, "uusimaa", "row-rented") for l in uusimaa_rented] +
        [_table_row_context(l, "uusimaa", "row-cand") for l in uusimaa_top5]
    )

    nb_sections = [s for s in [
        _section(f"PKS New Construction — Top {len(newbuild_pks)} (1 per building)",
                 f"Newly built / under-construction apartments in Helsinki, Espoo, Vantaa. "
                 f"Price ≤ {UUSIMAA_PRICE_MAX:,} €, loan ≤ {int(UUSIMAA_LOAN_RATIO_MAX*100)}%. "
                 "Deduplicated to one listing per building, then top scored by hub proximity.",
                 newbuild_pks, "sec-new", "uusimaa"),
    ] if s]
    nb_table_rows = [_table_row_context(l, "uusimaa", "row-confirmed") for l in newbuild_pks]

    ctx = {
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "price_max": PRICE_MAX,
        "loan_ratio_max_pct": int(LOAN_RATIO_MAX * 100),
        "max_stop_dist_m": MAX_STOP_DIST_M,
        "uusimaa_price_max": UUSIMAA_PRICE_MAX,
        "uusimaa_loan_ratio_max_pct": int(UUSIMAA_LOAN_RATIO_MAX * 100),
        "uusimaa_top_unrented": UUSIMAA_TOP_UNRENTED,
        "rented_count": len(rented_out),
        "new_count": len(new_cards),
        "pipe_count": len(pipe_cards),
        "cand_count": len(cand_cards),
        "uusimaa_rented_count": len(uusimaa_rented),
        "uusimaa_top5_count": len(uusimaa_top5),
        "newbuild_count": len(newbuild_pks),
        "tram_sections": tram_sections, "tram_table_rows": tram_table_rows,
        "uu_sections": uu_sections, "uu_table_rows": uu_table_rows,
        "nb_sections": nb_sections, "nb_table_rows": nb_table_rows,
        "tram_market_risks": TRAM_MARKET_RISKS,
        "uusimaa_market_risks": UUSIMAA_MARKET_RISKS,
    }

    html = _get_env().get_template("report.html.j2").render(**ctx)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Saved → {path}")
