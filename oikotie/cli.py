"""Entry point: orchestrates the three scrape pipelines (or serves the last
run from the results cache) and writes all report outputs."""

import json
import sys

from oikotie.cache import (
    load_json, load_results_cache, save_json, save_results_cache,
)
from oikotie.config import (
    CACHE_FILE, DATA_DIR, DOWN_PAYMENT_EUR, GEO_CACHE_FILE, LOAN_RATIO_MAX,
    NEWBUILD_TOP_N, PRICE_MAX, UUSIMAA_LOAN_RATIO_MAX, UUSIMAA_PRICE_MAX,
    UUSIMAA_TOP_UNRENTED,
)
from oikotie.csv_report import generate_csv_report
from oikotie.html_report import generate_html_report
from oikotie.pipelines import (
    classify_tram, dedupe_and_rank_newbuild, geocode_and_score_newbuild,
    geocode_tram_listings, geocode_uusimaa_listings, prefilter_uusimaa,
    score_and_rank_tram, score_and_rank_uusimaa,
)
from oikotie.scoring import _loan_ratio_str, monthly_mortgage
from oikotie.scraping import run_newbuild_scrape, run_tram_scrape, run_uusimaa_scrape


def fmt_eur_console(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.0f} €".replace(",", " ")
    except Exception:
        return str(v)


def _serve_from_results_cache(cached: dict) -> None:
    print(f"Using results cache (saved {cached['timestamp']}).")
    print("Pass --force to bypass and run the full pipeline.\n")
    confirmed       = cached["confirmed"]
    candidates      = cached["candidates"]
    tram_rented_out = cached["tram_rented_out"]
    uusimaa_rented  = cached["uusimaa_rented"]
    uusimaa_top5    = cached["uusimaa_top5"]
    uusimaa_passing = cached["uusimaa_passing"]
    newbuild_pks    = cached.get("newbuild_pks", [])

    with open(DATA_DIR / "results_tram.json", "w", encoding="utf-8") as fh:
        json.dump(confirmed + candidates, fh, ensure_ascii=False, indent=2)
    with open(DATA_DIR / "results_uusimaa.json", "w", encoding="utf-8") as fh:
        json.dump(uusimaa_passing, fh, ensure_ascii=False, indent=2)
    with open(DATA_DIR / "results_newbuild.json", "w", encoding="utf-8") as fh:
        json.dump(newbuild_pks, fh, ensure_ascii=False, indent=2)

    generate_csv_report(confirmed, candidates, path=str(DATA_DIR / "results_tram.csv"))
    generate_csv_report(uusimaa_rented, uusimaa_top5, path=str(DATA_DIR / "results_uusimaa.csv"))
    generate_html_report(confirmed, candidates, tram_rented_out,
                         uusimaa_rented, uusimaa_top5, newbuild_pks)


def _run_full_pipeline() -> None:
    from playwright.sync_api import sync_playwright

    print("Starting Playwright (WebKit) …")
    cache = load_json(CACHE_FILE)

    with sync_playwright() as pw:
        browser = pw.webkit.launch(headless=True)
        page = browser.new_page()

        tram_to_check = run_tram_scrape(page, cache, PRICE_MAX)
        save_json(CACHE_FILE, cache)

        uu_to_check = run_uusimaa_scrape(page, cache, UUSIMAA_PRICE_MAX)
        save_json(CACHE_FILE, cache)

        nb_to_check = run_newbuild_scrape(page, cache, UUSIMAA_PRICE_MAX)
        save_json(CACHE_FILE, cache)

        browser.close()

    geo_cache = load_json(GEO_CACHE_FILE)

    # ── Tram: geocode + classify + score ─────────────────────────────────
    tram_geocoded = geocode_tram_listings(tram_to_check, cache, geo_cache)
    save_json(GEO_CACHE_FILE, geo_cache)

    confirmed, candidates = classify_tram(tram_geocoded, PRICE_MAX, LOAN_RATIO_MAX)
    tram_rented_out = score_and_rank_tram(confirmed, candidates)
    print(f"\nTram — Confirmed: {len(confirmed)}  |  "
          f"Candidates: {len(candidates)}  |  Rented out: {len(tram_rented_out)}")

    # ── Uusimaa: pre-filter (no geo needed) → geocode survivors → score ──
    uu_pre = prefilter_uusimaa(uu_to_check, UUSIMAA_PRICE_MAX, UUSIMAA_LOAN_RATIO_MAX)
    uu_geocoded = geocode_uusimaa_listings(uu_pre, cache, geo_cache)
    save_json(GEO_CACHE_FILE, geo_cache)
    save_json(CACHE_FILE, cache)  # persist geo fields written back during this run

    uu_passing, uusimaa_rented, uusimaa_top5 = score_and_rank_uusimaa(uu_geocoded, UUSIMAA_TOP_UNRENTED)
    print(f"Uusimaa — Passing: {len(uu_passing)}  |  "
          f"Rented out: {len(uusimaa_rented)}  |  Watch list: {len(uusimaa_top5)}")

    # ── New build: geocode + score + dedupe ──────────────────────────────
    newbuild_scored = geocode_and_score_newbuild(nb_to_check, cache, geo_cache, UUSIMAA_LOAN_RATIO_MAX)
    save_json(GEO_CACHE_FILE, geo_cache)
    save_json(CACHE_FILE, cache)
    newbuild_pks = dedupe_and_rank_newbuild(newbuild_scored, NEWBUILD_TOP_N)

    # ── Results cache ─────────────────────────────────────────────────────
    save_results_cache(confirmed, candidates, tram_rented_out,
                       uusimaa_rented, uusimaa_top5, uu_passing, newbuild_pks)

    # ── Outputs ───────────────────────────────────────────────────────────
    all_tram_out = confirmed + candidates
    with open(DATA_DIR / "results_tram.json", "w", encoding="utf-8") as fh:
        json.dump(all_tram_out, fh, ensure_ascii=False, indent=2)
    print(f"Saved → {DATA_DIR / 'results_tram.json'}  ({len(all_tram_out)} listings)")

    with open(DATA_DIR / "results_uusimaa.json", "w", encoding="utf-8") as fh:
        json.dump(uu_passing, fh, ensure_ascii=False, indent=2)
    print(f"Saved → {DATA_DIR / 'results_uusimaa.json'}  ({len(uu_passing)} listings)")

    with open(DATA_DIR / "results_newbuild.json", "w", encoding="utf-8") as fh:
        json.dump(newbuild_pks, fh, ensure_ascii=False, indent=2)
    print(f"Saved → {DATA_DIR / 'results_newbuild.json'}  ({len(newbuild_pks)} listings)")

    generate_csv_report(confirmed, candidates, path=str(DATA_DIR / "results_tram.csv"))
    generate_csv_report(uusimaa_rented, uusimaa_top5, path=str(DATA_DIR / "results_uusimaa.csv"))
    generate_html_report(confirmed, candidates, tram_rented_out,
                         uusimaa_rented, uusimaa_top5, newbuild_pks)

    _print_console_summary(confirmed, candidates, tram_rented_out, uusimaa_rented, uusimaa_top5)


def _print_console_summary(confirmed, candidates, tram_rented_out, uusimaa_rented, uusimaa_top5) -> None:
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


def main() -> None:
    force = "--force" in sys.argv

    if not force:
        cached = load_results_cache()
        if cached is not None:
            _serve_from_results_cache(cached)
            return

    _run_full_pipeline()
