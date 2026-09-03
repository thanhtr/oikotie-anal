#!/usr/bin/env python3.10
"""Oikotie scraper — Playwright/WebKit, no context.dev.

Searches all 15 Vantaan ratikka corridor districts in one query,
paginates through every result page, then verifies loan & pipe
renovation on individual listing pages with a disk cache. Also runs
the Uusimaa (PKS-wide) and PKS-newbuild pipelines.

Criteria:
  - Kerrostalo only (buildingType=1)
  - 1–2 rooms
  - Velaton hinta ≤ 200 000 €
  - Housing company loan ≤ 50 % of debt-free price
  - Built ≥ 2000  OR  older with confirmed pipe renovation

Outputs: results_*.json, results_*.csv, index.html (see oikotie/ package)
Cache:   listing_cache.json  (individual page checks, survives re-runs)

Usage:
    python3.10 scraper.py [--force]
"""

from oikotie.cli import main

if __name__ == "__main__":
    main()
