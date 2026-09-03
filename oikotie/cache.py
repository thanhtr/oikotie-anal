"""Disk-backed JSON caches: listing details, geocode results, and the
TTL-bounded results cache used for the "serve from last run" fast path."""

import json
from datetime import datetime
from pathlib import Path

from oikotie.config import RESULTS_CACHE_FILE, RESULTS_CACHE_TTL_HOURS


def load_json(path: Path) -> dict:
    try:
        return json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def load_results_cache() -> dict | None:
    try:
        data = json.load(open(RESULTS_CACHE_FILE, encoding="utf-8"))
        age_h = (datetime.now() - datetime.fromisoformat(data["timestamp"])).total_seconds() / 3600
        if age_h <= RESULTS_CACHE_TTL_HOURS:
            return data
        print(f"Results cache expired ({age_h:.1f}h old, TTL={RESULTS_CACHE_TTL_HOURS}h) — running full pipeline.")
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def save_results_cache(confirmed: list, candidates: list, tram_rented_out: list,
                       uusimaa_rented: list, uusimaa_top5: list,
                       uusimaa_passing: list, newbuild_pks: list) -> None:
    data = {
        "timestamp":       datetime.now().isoformat(),
        "confirmed":       confirmed,
        "candidates":      candidates,
        "tram_rented_out": tram_rented_out,
        "uusimaa_rented":  uusimaa_rented,
        "uusimaa_top5":    uusimaa_top5,
        "uusimaa_passing": uusimaa_passing,
        "newbuild_pks":    newbuild_pks,
    }
    with open(RESULTS_CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print(f"Saved → {RESULTS_CACHE_FILE}  (valid for {RESULTS_CACHE_TTL_HOURS}h)")
