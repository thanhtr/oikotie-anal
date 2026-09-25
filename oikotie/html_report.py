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
    CO_LOAN_RATE, DATA_DIR, DEDUCTION_ENABLED, DOWN_PAYMENT_EUR, LL_HOLD_YEARS,
    LL_MAX_AGE_YEARS, LL_MIN_LOAN_RATIO, LL_MYYNTI_MAX, LOAN_RATIO_MAX,
    MAX_STOP_DIST_M, PRICE_MAX, STOP_LINKS, STOP_NOTE, TAX_RATE,
    TRAM_MARKET_RISKS, UUSIMAA_LOAN_RATIO_MAX, UUSIMAA_MARKET_RISKS,
    UUSIMAA_PRICE_MAX, UUSIMAA_TOP_UNRENTED,
)
from oikotie.pipelines import (
    listing_red_flags, listing_red_flags_largeloan, listing_red_flags_uusimaa,
)
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


def _pct(v, digits: int = 1) -> str:
    return "—" if v is None else f"{v*100:.{digits}f}%"


_BOOKING_BADGE = {
    "yes":     {"cls": "new",  "text": "tuloutus ✓"},
    "unknown": {"cls": "cand", "text": "tuloutus ?"},
    "no":      {"cls": "rent", "text": "rahastointi"},
}


def _largeloan_context(l: dict) -> dict:
    """Extra card fields for the large-loan view (merged into _card_context)."""
    yes = l.get("booking_method") == "yes"
    benefit = l.get("tax_benefit_yr") if yes else l.get("tax_benefit_if_yes")
    lifetime = l.get("lifetime_net_benefit") if yes else l.get("lifetime_net_benefit_if_yes")
    timing = l.get("timing_value") if yes else l.get("timing_value_if_yes")
    suffix = "" if yes else " if tuloutus"
    rows = [
        ("Loan share", f"{fmt_eur(l.get('loan_share_eur'))} ({_pct(l.get('loan_ratio'), 0)} of velaton)"),
        ("Rahoitusvastike", f"{fmt_eur(l.get('rahoitusvastike_eur_month'))}/kk"
         + (f" (grace {fmt_eur(l.get('rahoitusvastike_grace_eur_month'))}/kk"
            + (f" → {l['grace_end_year']}" if l.get("grace_end_year") else "") + ")"
            if l.get("rahoitusvastike_grace_eur_month") is not None else "")),
        ("Principal est.", f"{fmt_eur(l.get('principal_est_yr'))}/yr ({_pct(l.get('principal_pct'))} of loan)"),
        ("Tax benefit", f"{fmt_eur(benefit)}/yr{suffix}"),
        ("Rent est.", f"{fmt_eur(l.get('est_rent_month'))}/mo · {l.get('rent_source', '')}"),
        ("After-tax CF", f"{fmt_eur(l.get('after_tax_cf_yr'))}/yr"),
        (f"Net {LL_HOLD_YEARS}-yr benefit", f"{fmt_eur(lifetime)} after sale-gain recapture"
                                            f" + {fmt_eur(timing)} timing value{suffix}"),
    ]
    bd = l.get("score_breakdown") or {}
    parts = bd.get("parts") or {}
    transit = bd.get("transit")
    return {
        "headline_price_s": fmt_eur(l.get("price_eur")),
        "headline_sub": f"myyntihinta · velaton {fmt_eur(l.get('debt_free_price_eur'))}",
        "yield_str": f"{_pct(l.get('cash_yield'))} after-tax cash yield",
        "ll_rows": [{"k": k, "v": v} for k, v in rows],
        "score_parts": " · ".join(f"{k} {v}" for k, v in parts.items()),
        "note": ({"text": f"🚧 {transit['name']} {transit['dist']} m — {transit['note']}",
                  "links": [{"url": transit["url"], "label": "source"}]} if transit else None),
        "booking_info": l.get("booking_info") or "",
        "grace_info": l.get("grace_period_info") or "",
    }


def _status_badge(l: dict) -> dict:
    tag = l.get("_search_pass", "")
    if tag == "new-build-large-loan":
        return _BOOKING_BADGE.get(l.get("booking_method") or "unknown", _BOOKING_BADGE["unknown"])
    if tag == "new_house_2000plus":
        return {"cls": "new", "text": f"built {l.get('year_built', '')}"}
    if tag == "candidate_check_pipe_reno":
        return {"cls": "cand", "text": f"built {l.get('year_built', '')} · verify pipe"}
    reno_yr = l.get("pipe_renovation_year")
    label = f"pipe reno {reno_yr}" if reno_yr else "pipe reno ✓"
    return {"cls": "reno", "text": label}


def _card_context(l: dict, mode: str) -> dict:
    """Build the render context for one listing card. `mode` is "tram",
    "uusimaa" or "largeloan" — it only decides which optional fields get populated."""
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
        flags = listing_red_flags_largeloan(l) if mode == "largeloan" else listing_red_flags_uusimaa(l)

    ctx = {
        "url": url, "full_addr": full_addr, "rank_s": rank_s, "price_s": price_s,
        "price_sub": "velaton",
        "loan_s": loan_s, "monthly_str": monthly_str, "yield_str": yield_str,
        "meta_s": meta_s, "badges": badges, "note": note,
        "hub_line": hub_line, "mall_line": mall_line,
        "flags": [{"text": t, "url": u, "label": lb} for t, u, lb in flags],
        "reno": l.get("pipe_renovation_info") or "",
    }
    if mode == "largeloan":
        ll = _largeloan_context(l)
        ctx.update({
            "price_s": ll["headline_price_s"], "price_sub": ll["headline_sub"],
            "loan_s": None, "monthly_str": None, "yield_str": ll["yield_str"],
            "ll_rows": ll["ll_rows"], "score_parts": ll["score_parts"],
            "note": ll["note"], "reno": "",
            "booking_info": ll["booking_info"], "grace_info": ll["grace_info"],
        })
    return ctx


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
    if mode == "largeloan":
        ctx.update({
            "dfp_s": fmt_eur(l.get("price_eur")),
            "loan_s": _pct(l.get("loan_ratio"), 0),
            "fin_s": fmt_eur(l.get("rahoitusvastike_eur_month")),
            "booking": l.get("booking_method") or "unknown",
            "tax_s": fmt_eur(l.get("tax_benefit_yr") if l.get("booking_method") == "yes"
                             else l.get("tax_benefit_if_yes")),
            "yield_s": _pct(l.get("cash_yield")),
            "score": l.get("score", "—"),
        })
        return ctx
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
                         largeloan: list[dict] = None,
                         path=None) -> None:
    if path is None:
        path = DATA_DIR / "index.html"
    rented_out     = rented_out     or []
    uusimaa_rented = uusimaa_rented or []
    uusimaa_top5   = uusimaa_top5   or []
    largeloan      = largeloan      or []

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

    ll_yes     = [l for l in largeloan if l.get("booking_method") == "yes"]
    ll_unknown = [l for l in largeloan if l.get("booking_method") != "yes"]
    caveat = ("Screening aid, not tax advice. The interest/principal split is estimated "
              f"at {CO_LOAN_RATE*100:.1f}% company-loan rate; booking method is a text hint only.")
    nb_sections = [s for s in [
        _section("Full match — tuloutus stated in listing",
                 "Financing charge is booked as income, so the whole rahoitusvastike "
                 "(principal included) is deductible from rental income. " + caveat,
                 ll_yes, "sec-new", "largeloan"),
        _section("Booking method unverified",
                 "Tuloutus vs rahastointi not stated. Confirm in the myyntiesite or "
                 "isännöitsijäntodistus before treating as a match — figures shown "
                 "'if tuloutus' are the upside. " + caveat,
                 ll_unknown, "sec-cand", "largeloan"),
    ] if s]
    nb_table_rows = [_table_row_context(l, "largeloan",
                                        "row-confirmed" if l.get("booking_method") == "yes" else "row-cand")
                     for l in largeloan]

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
        "newbuild_count": len(largeloan),
        "ll_yes_count": len(ll_yes),
        "ll_myynti_max": LL_MYYNTI_MAX,
        "ll_min_loan_pct": int(LL_MIN_LOAN_RATIO * 100),
        "ll_max_age": LL_MAX_AGE_YEARS,
        "ll_hold_years": LL_HOLD_YEARS,
        "ll_tax_pct": int(round(TAX_RATE * 100)),
        "ll_rate_pct": f"{CO_LOAN_RATE*100:.1f}",
        "ll_deduction_enabled": DEDUCTION_ENABLED,
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
