"""Oikotie search URL builders and the matching result-card link selectors."""

import json
import urllib.parse

from oikotie.config import (
    BASE_URL, LL_SEARCH_VELATON_MAX, PRICE_MAX, TRAMLINE_LOCATIONS,
    UUSIMAA_LOCATIONS, UUSIMAA_PRICE_MAX,
)


def build_search_url(page_num: int = 1) -> str:
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
    """PKS new developments, all room counts. Oikotie's price filter is not
    myyntihinta, so the cap here only bounds scrape size — the real
    myyntihinta filter runs after detail fetch (largeloan.qualifies)."""
    loc = urllib.parse.quote(json.dumps(UUSIMAA_LOCATIONS))
    price = f"&price[max]={LL_SEARCH_VELATON_MAX}" if LL_SEARCH_VELATON_MAX else ""
    return (
        f"{BASE_URL}/myytavat-asunnot"
        f"?pagination={page_num}"
        f"&cardType=100"
        f"&newDevelopment=1"
        f"&locations={loc}"
        f"&habitationType[]=1"
        f"{price}"
    )


TRAM_LINK_SELECTOR     = 'a[href*="/myytavat-asunnot/vantaa/"], a[href*="/myytavat-asunnot/helsinki/"]'
UUSIMAA_LINK_SELECTOR  = 'a[href*="/myytavat-asunnot/helsinki/"], a[href*="/myytavat-asunnot/espoo/"], a[href*="/myytavat-asunnot/vantaa/"]'
NEWBUILD_LINK_SELECTOR = 'a[href*="/myytavat-asunnot/helsinki/"], a[href*="/myytavat-asunnot/espoo/"], a[href*="/myytavat-asunnot/vantaa/"], a[href*="/myytavat-uudisasunnot/"]'
