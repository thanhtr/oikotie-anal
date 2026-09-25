"""CSV export for the tram, Uusimaa and large-loan result sets."""

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


LL_CSV_FIELDS = [
    "rank", "score", "is_rented_out", "rental_income_eur_month", "address", "district", "city",
    "price_eur", "debt_free_price_eur", "loan_share_eur", "loan_ratio",
    "room_count", "size_sqm", "year_built", "completion_year",
    "hoitovastike_eur_month", "rahoitusvastike_eur_month", "rahoitusvastike_grace_eur_month",
    "grace_end_year", "booking_method",
    "interest_est_yr", "principal_est_yr", "principal_pct",
    "tax_benefit_yr", "tax_benefit_if_yes",
    "est_rent_month", "rent_source", "pre_tax_cf_yr", "after_tax_cf_yr", "cash_yield",
    "lifetime_net_benefit", "lifetime_net_benefit_if_yes", "timing_value", "timing_value_if_yes",
    "nearest_hub", "hub_distance_m", "helsinki_central_km",
    "listing_url",
]


def generate_csv_report(confirmed: list[dict], candidates: list[dict],
                        path: str = "results.csv", fields: list[str] = CSV_FIELDS) -> None:
    rows = confirmed + candidates
    if not rows:
        open(path, "w").write(",".join(fields) + "\n")
        print(f"Saved → {path}  (empty)")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Saved → {path}  ({len(rows)} rows)")
