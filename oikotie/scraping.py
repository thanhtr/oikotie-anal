"""Playwright-driven scraping: search-result pages and per-listing detail
fetches, plus the three pipeline-specific scrape runners."""

import re

from oikotie.config import BASE_URL, LL_MIN_LOAN_RATIO, LL_MYYNTI_MAX, MAX_DETAIL_CHECKS
from oikotie.largeloan import is_recent_build, loan_share, prequalifies
from oikotie.parsing import fetch_listing_details, parse_card_text
from oikotie.urls import (
    NEWBUILD_LINK_SELECTOR, TRAM_LINK_SELECTOR, UUSIMAA_LINK_SELECTOR,
    build_newbuild_search_url, build_search_url, build_uusimaa_search_url,
)


def scrape_search_page(page, page_num: int,
                       url_builder=None,
                       link_selector: str = None) -> tuple[list[dict], int, int]:
    """Load one results page; return (listings, total_count, total_pages)."""
    url_builder   = url_builder   or build_search_url
    link_selector = link_selector or TRAM_LINK_SELECTOR
    url = url_builder(page_num)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    # Wait for JS-rendered listings; on a truly empty page this resolves via timeout
    try:
        page.wait_for_selector(link_selector, timeout=20000)
    except Exception:
        pass
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


def _scrape_all_pages(page, url_builder, link_selector, label: str) -> list[dict]:
    """Paginate a search until no more pages, deduping by listing URL."""
    raw: list[dict] = []
    seen: set[str] = set()
    total_pages = None
    p = 1
    while True:
        print(f"  Page {p}" + (f"/{total_pages}" if total_pages else "") + " …", end=" ", flush=True)
        listings, total, total_pages = scrape_search_page(page, p, url_builder, link_selector)
        new = 0
        for l in listings:
            u = l.get("listing_url", "")
            if u and u not in seen:
                seen.add(u)
                raw.append(l)
                new += 1
        print(f"{new} new  (total so far: {len(raw)}/{total})")
        if p >= total_pages:
            break
        p += 1
    print(f"\n{label} raw listings (deduped): {len(raw)}")
    return raw


def _fetch_details_for(page, listings: list[dict], cache: dict, label: str,
                       require_key: str = "hoitovastike_eur_month") -> None:
    """Fetch and merge individual-listing details in place."""
    if not listings:
        return
    print(f"\n  Fetching details for {len(listings)} {label} listings …")
    newly = 0
    for idx, listing in enumerate(listings, 1):
        url = listing["listing_url"]
        cached = url in cache and require_key in cache[url]
        name = listing.get("address") or url.split("/")[-1]
        print(f"  [{idx:2d}/{len(listings)}] {'(cache) ' if cached else ''}{name}")
        details = fetch_listing_details(page, url, cache, require_key)
        listing.update({k: v for k, v in details.items() if v is not None})
        if not cached:
            newly += 1
    print(f"  {newly} fresh fetches, {len(listings)-newly} from cache")


def run_tram_scrape(page, cache: dict, price_max: float) -> list[dict]:
    print(f"\nTRAM PIPELINE: scraping tram-corridor districts, price ≤ {price_max:,.0f} €")
    raw = _scrape_all_pages(page, build_search_url, TRAM_LINK_SELECTOR, "Tram")
    initial = [l for l in raw if (l.get("price_eur") or 999_999) <= price_max]
    print(f"After initial filter (≤{price_max:,.0f} €): {len(initial)}")
    to_check = [l for l in initial if l.get("listing_url")][:MAX_DETAIL_CHECKS]
    _fetch_details_for(page, to_check, cache, "tram")
    return to_check


def run_uusimaa_scrape(page, cache: dict, price_max: float) -> list[dict]:
    print(f"\nPKS PIPELINE: Helsinki / Espoo / Vantaa, price ≤ {price_max:,.0f} €")
    raw = _scrape_all_pages(page, build_uusimaa_search_url, UUSIMAA_LINK_SELECTOR, "Uusimaa")
    initial = [l for l in raw if (l.get("price_eur") or 999_999) <= price_max]
    print(f"After initial filter (≤{price_max:,.0f} €): {len(initial)}")
    to_check = [l for l in initial if l.get("listing_url")][:MAX_DETAIL_CHECKS]
    _fetch_details_for(page, to_check, cache, "Uusimaa")
    return to_check


def run_newbuild_scrape(page, cache: dict, extra: list[dict] = ()) -> list[dict]:
    """Large-loan pool: PKS new developments (all sizes) + recent builds from
    `extra` (the PKS scrape). Details are (re-)fetched so the financing-charge
    fields exist; the myyntihinta / loan-ratio gate runs later."""
    print(f"\nLARGE-LOAN PIPELINE: PKS new construction, myyntihinta ≤ {LL_MYYNTI_MAX:,.0f} €")
    raw: list[dict] = []
    seen: set[str] = set()
    total_pages = None
    p = 1
    while total_pages is None or p <= total_pages:
        listings, total, total_pages = scrape_search_page(
            page, p, build_newbuild_search_url, NEWBUILD_LINK_SELECTOR,
        )
        new = [l for l in listings if l.get("listing_url") not in seen]
        for l in new:
            seen.add(l.get("listing_url", ""))
        raw.extend(new)
        print(f"  Page {p}/{total_pages} … {len(new)} new  (total so far: {len(raw)}/{total})")
        if not new:
            break
        p += 1

    # Copies: these dicts are shared with the Uusimaa pipeline, which sets its own score/rank
    extra_recent = [dict(l) for l in extra if l.get("listing_url") not in seen and is_recent_build(l)]
    pool = [l for l in raw + extra_recent if l.get("listing_url") and prequalifies(l)]
    print(f"New-dev raw: {len(raw)}  |  + recent PKS builds: {len(extra_recent)}  |  pool: {len(pool)}")
    # Pre-screen with cached details so only plausible large-loan flats get re-fetched
    to_fetch = []
    for l in pool:
        c = cache.get(l["listing_url"], {})
        if "rahoitusvastike_eur_month" in c or "hoitovastike_eur_month" not in c:
            to_fetch.append(l)
            continue
        merged = {**l, **{k: v for k, v in c.items() if v is not None}}
        share, dfp = loan_share(merged), merged.get("debt_free_price_eur")
        if share is None or not dfp or share / float(dfp) >= LL_MIN_LOAN_RATIO:
            to_fetch.append(l)
    print(f"  After cached loan-ratio pre-screen: {len(to_fetch)}")
    _fetch_details_for(page, to_fetch, cache, "large-loan", require_key="rahoitusvastike_eur_month")
    return to_fetch
