"""CSV export for the tram and Uusimaa result sets."""

import csv

CSV_FIELDS = [
    "address", "district", "city",
    "price_eur", "debt_free_price_eur", "housing_company_loan_eur",
    "room_count", "size_sqm", "floor",
    "year_built", "property_type",
    "pipe_renovation_done", "pipe_renovation_year", "pipe_renovation_info",
    "is_rented_out",
    "monthly_cost_eur", "hoitovastike_eur_month", "tonttivuokra_eur_month",
    "score", "rank", "nearest_stop", "distance_m", "lat", "lon",
    "_search_pass",
    "listing_url",
]


def generate_csv_report(confirmed: list[dict], candidates: list[dict],
                        path: str = "results.csv") -> None:
    rows = confirmed + candidates
    if not rows:
        open(path, "w").write(",".join(CSV_FIELDS) + "\n")
        print(f"Saved → {path}  (empty)")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Saved → {path}  ({len(rows)} rows)")
