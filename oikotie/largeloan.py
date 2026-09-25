"""Large-loan new-build metrics: housing-company loan share, principal estimate,
tuloutus tax benefit, after-tax cash yield and a simple lifetime (sale-gain
recapture) estimate. A screening aid, not tax advice — the interest/principal
split is estimated and the booking method is only a text hint."""

from datetime import datetime

from oikotie.config import (
    APPRECIATION_RATE, CO_LOAN_RATE, DEDUCTION_ENABLED, LL_HOLD_YEARS,
    LL_MAX_AGE_YEARS, LL_MIN_LOAN_RATIO, LL_MIN_PRINCIPAL_PCT, LL_MYYNTI_MAX,
    LL_REINVEST_RATE, TAX_RATE,
)


def loan_share(l: dict) -> float | None:
    """Housing-company loan share: listed Velkaosuus, else velaton − myynti."""
    loan = l.get("housing_company_loan_eur")
    if loan:
        return float(loan)
    dfp, price = l.get("debt_free_price_eur"), l.get("price_eur")
    if dfp and price and float(dfp) > float(price):
        return float(dfp) - float(price)
    return 0.0 if loan == 0 else None


def _gain_tax(sale_price: float, acq: float, hold_years: int) -> float:
    olettama = (0.40 if hold_years >= 10 else 0.20) * sale_price   # hankintameno-olettama
    return max(sale_price - max(acq, olettama), 0.0) * TAX_RATE


def compute_largeloan_metrics(l: dict, rent_month: float | None) -> dict:
    myynti = float(l.get("price_eur") or 0)
    dfp    = float(l.get("debt_free_price_eur") or 0) or myynti + (loan_share(l) or 0)
    share  = loan_share(l) or 0.0
    fin_yr = float(l.get("rahoitusvastike_eur_month") or 0) * 12
    hoito_yr = (float(l.get("hoitovastike_eur_month") or 0)
                + float(l.get("tonttivuokra_eur_month") or 0)) * 12
    booking = l.get("booking_method") or "unknown"

    interest_est  = share * CO_LOAN_RATE
    principal_est = max(fin_yr - interest_est, 0.0)
    principal_benefit = principal_est * TAX_RATE if DEDUCTION_ENABLED else 0.0
    tuloutus = booking == "yes" and DEDUCTION_ENABLED

    m: dict = {
        "loan_share_eur":     round(share),
        "loan_ratio":         round(share / dfp, 3) if dfp > 0 else None,
        "interest_est_yr":    round(interest_est),
        "principal_est_yr":   round(principal_est),
        "principal_pct":      round(principal_est / share, 4) if share > 0 else 0.0,
        "tax_benefit_yr":     round(principal_benefit) if tuloutus else 0,
        "tax_benefit_if_yes": round(principal_benefit),
        "est_rent_month":     rent_month,
    }

    if rent_month and myynti > 0:
        rent_yr = rent_month * 12
        pre_tax_cf = rent_yr - hoito_yr - fin_yr
        # With tuloutus the whole charge is deductible; otherwise only the interest
        # share is counted (conservative; a rahastoitu charge is not deductible at all).
        deduct = fin_yr if tuloutus else interest_est
        taxable = rent_yr - hoito_yr - deduct
        after_tax_cf = pre_tax_cf - max(taxable, 0.0) * TAX_RATE
        m.update({
            "pre_tax_cf_yr":   round(pre_tax_cf),
            "after_tax_cf_yr": round(after_tax_cf),
            "cash_yield":      round(after_tax_cf / myynti, 4),
        })
    else:
        m.update({"pre_tax_cf_yr": None, "after_tax_cf_yr": None, "cash_yield": None})

    # Lifetime: deducting principal now keeps the acquisition cost at myyntihinta,
    # so the eventual sale gain is larger. Comparator: principal not deducted but
    # added to the cost basis. Net = upfront deductions − extra gain tax; when
    # the olettama doesn't bind these cancel, and the real gain is timing:
    # each year's tax saving compounds at LL_REINVEST_RATE until the sale.
    h = LL_HOLD_YEARS
    principal_paid = min(principal_est * h, share)
    sale_price = dfp * (1 + APPRECIATION_RATE) ** h - (share - principal_paid)
    extra_gain_tax = (_gain_tax(sale_price, myynti, h)
                      - _gain_tax(sale_price, myynti + principal_paid, h))
    net = principal_benefit * h - extra_gain_tax
    timing = sum(principal_benefit * ((1 + LL_REINVEST_RATE) ** (h - t) - 1) for t in range(1, h + 1))
    m["lifetime_net_benefit_if_yes"] = round(net)
    m["lifetime_net_benefit"] = round(net) if tuloutus else 0
    m["timing_value_if_yes"] = round(timing)
    m["timing_value"] = round(timing) if tuloutus else 0
    return m


def is_recent_build(l: dict) -> bool:
    year = l.get("year_built") or l.get("completion_year")
    if year:
        return int(year) >= datetime.now().year - LL_MAX_AGE_YEARS
    return bool(l.get("is_new_development"))


def prequalifies(l: dict) -> bool:
    """Cheap card-level filter run before the detail fetch. The card price may
    be velaton, so price is only checked once myyntihinta is known."""
    return is_recent_build(l) or not l.get("year_built")


def qualifies(l: dict) -> bool:
    """Full gate — needs detail fields and computed metrics in `l`."""
    myynti = float(l.get("price_eur") or 0)
    if not myynti or myynti > LL_MYYNTI_MAX:
        return False
    if (l.get("loan_ratio") or 0) < LL_MIN_LOAN_RATIO:
        return False
    if not is_recent_build(l):
        return False
    if l.get("booking_method") == "no":
        return False
    grace_end = l.get("grace_end_year")
    amortising = (l.get("principal_pct") or 0) >= LL_MIN_PRINCIPAL_PCT
    grace_ok = grace_end is not None and grace_end <= datetime.now().year + LL_HOLD_YEARS
    return amortising or grace_ok
