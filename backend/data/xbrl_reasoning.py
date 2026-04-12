"""Deterministic reasoning helpers over SEC XBRL company facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .xbrl_fetcher import get_metric, search_metric


@dataclass
class ComputedAnswer:
    """Structured numeric answer with provenance and derivation details."""

    operation: str
    ticker: str
    years: list[int]
    metrics: list[str]
    value: float | bool | None
    formatted_value: str
    unit: str
    concepts: list[str]
    derivation_steps: list[str]
    citations: list[dict[str, str | int]]


def _format_numeric(value: float, unit: str) -> str:
    if unit == "USD/shares":
        return f"${value:,.2f} per share"
    if unit == "shares":
        if abs(value) >= 1_000_000_000:
            return f"{value / 1_000_000_000:,.2f} billion shares"
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:,.1f} million shares"
        return f"{value:,.0f} shares"
    if unit == "pure":
        if abs(value) <= 10:
            return f"{value:.2f}"
        return f"{value:,.2f}"
    abs_val = abs(value)
    if abs_val >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.2f} billion"
    if abs_val >= 1_000_000:
        return f"${value / 1_000_000:,.1f} million"
    return f"${value:,.2f}"


def _fact_citation(fact) -> dict[str, str | int]:
    return {
        "concept": fact.concept,
        "year": fact.fiscal_year,
        "period": fact.fiscal_period,
        "form": fact.form,
        "filed": fact.filed,
    }


def _average_facts(facts: list) -> tuple[float, str, list[str], list[dict[str, str | int]]] | None:
    if not facts:
        return None
    values = [float(fact.value) for fact in facts]
    return (
        sum(values) / len(values),
        facts[0].unit,
        [fact.concept for fact in facts],
        [_fact_citation(fact) for fact in facts],
    )


def _resolve_fact(ticker: str, metric: str, year: int, period: str = "FY"):
    fact = get_metric(ticker, metric, year, period=period)
    if fact is not None:
        return fact

    # Fallback to fuzzy concept matching for company-specific concept names.
    candidates = search_metric(ticker, metric, year, period=period)
    if candidates:
        return candidates[0]
    return None


def direct_lookup(ticker: str, metric: str, year: int, period: str = "FY") -> ComputedAnswer | None:
    fact = _resolve_fact(ticker, metric, year, period=period)
    if fact is None:
        return None
    return ComputedAnswer(
        operation="lookup",
        ticker=ticker.upper(),
        years=[year],
        metrics=[metric.lower()],
        value=fact.value,
        formatted_value=_format_numeric(float(fact.value), fact.unit),
        unit=fact.unit,
        concepts=[fact.concept],
        derivation_steps=[
            f"Resolved metric '{metric}' to XBRL concept '{fact.concept}'.",
            f"Selected {fact.form} {fact.fiscal_period}{fact.fiscal_year} fact value {fact.value}.",
        ],
        citations=[_fact_citation(fact)],
    )


def absolute_change(
    ticker: str,
    metric: str,
    start_year: int,
    end_year: int,
) -> ComputedAnswer | None:
    start = _resolve_fact(ticker, metric, start_year)
    end = _resolve_fact(ticker, metric, end_year)
    if start is None or end is None:
        return None

    delta = float(end.value) - float(start.value)
    return ComputedAnswer(
        operation="absolute_change",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=[metric.lower()],
        value=delta,
        formatted_value=_format_numeric(delta, end.unit),
        unit=end.unit,
        concepts=[start.concept, end.concept],
        derivation_steps=[
            f"Fetched {metric} for FY{start_year}: {start.value} ({start.concept}).",
            f"Fetched {metric} for FY{end_year}: {end.value} ({end.concept}).",
            f"Computed absolute change as {end.value} - {start.value} = {delta}.",
        ],
        citations=[_fact_citation(start), _fact_citation(end)],
    )


def percentage_change(
    ticker: str,
    metric: str,
    start_year: int,
    end_year: int,
) -> ComputedAnswer | None:
    start = _resolve_fact(ticker, metric, start_year)
    end = _resolve_fact(ticker, metric, end_year)
    if start is None or end is None:
        return None
    if float(start.value) == 0:
        return None

    pct = ((float(end.value) - float(start.value)) / abs(float(start.value))) * 100.0
    return ComputedAnswer(
        operation="percentage_change",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=[metric.lower()],
        value=pct,
        formatted_value=f"{pct:+.2f}%",
        unit="percent",
        concepts=[start.concept, end.concept],
        derivation_steps=[
            f"Fetched {metric} for FY{start_year}: {start.value} ({start.concept}).",
            f"Fetched {metric} for FY{end_year}: {end.value} ({end.concept}).",
            f"Computed percentage change as (({end.value} - {start.value}) / abs({start.value})) * 100 = {pct}.",
        ],
        citations=[_fact_citation(start), _fact_citation(end)],
    )


def ratio(
    ticker: str,
    numerator_metric: str,
    denominator_metric: str,
    year: int,
) -> ComputedAnswer | None:
    numerator = _resolve_fact(ticker, numerator_metric, year)
    denominator = _resolve_fact(ticker, denominator_metric, year)
    if numerator is None or denominator is None:
        return None
    if float(denominator.value) == 0:
        return None

    ratio_value = float(numerator.value) / float(denominator.value)
    return ComputedAnswer(
        operation="ratio",
        ticker=ticker.upper(),
        years=[year],
        metrics=[numerator_metric.lower(), denominator_metric.lower()],
        value=ratio_value,
        formatted_value=f"{ratio_value:.4f}",
        unit="ratio",
        concepts=[numerator.concept, denominator.concept],
        derivation_steps=[
            f"Fetched numerator {numerator_metric}: {numerator.value} ({numerator.concept}).",
            f"Fetched denominator {denominator_metric}: {denominator.value} ({denominator.concept}).",
            f"Computed ratio as {numerator.value} / {denominator.value} = {ratio_value}.",
        ],
        citations=[_fact_citation(numerator), _fact_citation(denominator)],
    )


def compare_years(
    ticker: str,
    metric: str,
    years: list[int] | tuple[int, ...],
) -> ComputedAnswer | None:
    facts = []
    for year in sorted(set(years)):
        fact = _resolve_fact(ticker, metric, year)
        if fact is None:
            return None
        facts.append(fact)

    parts = [
        f"FY{fact.fiscal_year}: {_format_numeric(float(fact.value), fact.unit)}"
        for fact in facts
    ]
    return ComputedAnswer(
        operation="compare",
        ticker=ticker.upper(),
        years=[fact.fiscal_year for fact in facts],
        metrics=[metric.lower()],
        value=None,
        formatted_value="; ".join(parts),
        unit=facts[0].unit,
        concepts=[fact.concept for fact in facts],
        derivation_steps=[
            f"Fetched {metric} for FY{fact.fiscal_year}: {fact.value} ({fact.concept})."
            for fact in facts
        ],
        citations=[_fact_citation(fact) for fact in facts],
    )


def metric_exists(ticker: str, metric: str, year: int) -> ComputedAnswer:
    fact = _resolve_fact(ticker, metric, year)
    exists = fact is not None
    citations = [_fact_citation(fact)] if fact is not None else []
    steps = [
        f"Looked up metric '{metric}' for FY{year}.",
        "A matching fact was found." if exists else "No matching fact was found.",
    ]
    return ComputedAnswer(
        operation="existence",
        ticker=ticker.upper(),
        years=[year],
        metrics=[metric.lower()],
        value=exists,
        formatted_value="yes" if exists else "no",
        unit="boolean",
        concepts=[fact.concept] if fact is not None else [],
        derivation_steps=steps,
        citations=citations,
    )


def ratio_with_average_denominator(
    ticker: str,
    numerator_metric: str,
    denominator_metric: str,
    start_year: int,
    end_year: int,
) -> ComputedAnswer | None:
    numerator = _resolve_fact(ticker, numerator_metric, end_year)
    start_den = _resolve_fact(ticker, denominator_metric, start_year)
    end_den = _resolve_fact(ticker, denominator_metric, end_year)
    if numerator is None or start_den is None or end_den is None:
        return None

    average_denominator = (float(start_den.value) + float(end_den.value)) / 2.0
    if average_denominator == 0:
        return None

    ratio_value = float(numerator.value) / average_denominator
    return ComputedAnswer(
        operation="ratio_avg_balance",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=[numerator_metric.lower(), denominator_metric.lower()],
        value=ratio_value,
        formatted_value=f"{ratio_value:.4f}",
        unit="ratio",
        concepts=[numerator.concept, start_den.concept, end_den.concept],
        derivation_steps=[
            f"Fetched numerator {numerator_metric} for FY{end_year}: {numerator.value} ({numerator.concept}).",
            f"Fetched denominator {denominator_metric} for FY{start_year}: {start_den.value} ({start_den.concept}).",
            f"Fetched denominator {denominator_metric} for FY{end_year}: {end_den.value} ({end_den.concept}).",
            f"Computed average denominator as ({start_den.value} + {end_den.value}) / 2 = {average_denominator}.",
            f"Computed ratio as {numerator.value} / {average_denominator} = {ratio_value}.",
        ],
        citations=[_fact_citation(numerator), _fact_citation(start_den), _fact_citation(end_den)],
    )


def three_year_average_ratio(
    ticker: str,
    numerator_metric: str,
    denominator_metric: str,
    years: list[int],
) -> ComputedAnswer | None:
    years = sorted(set(years))
    if len(years) < 3:
        return None

    annual_ratios = []
    concepts: list[str] = []
    citations: list[dict[str, str | int]] = []
    steps = []

    for year in years:
        numerator = _resolve_fact(ticker, numerator_metric, year)
        denominator = _resolve_fact(ticker, denominator_metric, year)
        if numerator is None or denominator is None or float(denominator.value) == 0:
            return None
        year_ratio = float(numerator.value) / float(denominator.value)
        annual_ratios.append(year_ratio)
        concepts.extend([numerator.concept, denominator.concept])
        citations.extend([_fact_citation(numerator), _fact_citation(denominator)])
        steps.append(
            f"FY{year}: {numerator_metric} / {denominator_metric} = "
            f"{numerator.value} / {denominator.value} = {year_ratio}."
        )

    average_ratio = sum(annual_ratios) / len(annual_ratios)
    steps.append(
        f"Computed {len(annual_ratios)}-year average ratio as "
        f"({', '.join(f'{r:.6f}' for r in annual_ratios)}) / {len(annual_ratios)} = {average_ratio}."
    )
    return ComputedAnswer(
        operation="three_year_avg_ratio",
        ticker=ticker.upper(),
        years=years,
        metrics=[numerator_metric.lower(), denominator_metric.lower()],
        value=average_ratio,
        formatted_value=f"{average_ratio:.4f}",
        unit="ratio",
        concepts=concepts,
        derivation_steps=steps,
        citations=citations,
    )


def cagr(
    ticker: str,
    metric: str,
    start_year: int,
    end_year: int,
) -> ComputedAnswer | None:
    start = _resolve_fact(ticker, metric, start_year)
    end = _resolve_fact(ticker, metric, end_year)
    if start is None or end is None:
        return None
    start_value = float(start.value)
    end_value = float(end.value)
    periods = end_year - start_year
    if start_value <= 0 or periods <= 0:
        return None

    cagr_value = ((end_value / start_value) ** (1.0 / periods) - 1.0) * 100.0
    return ComputedAnswer(
        operation="cagr",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=[metric.lower()],
        value=cagr_value,
        formatted_value=f"{cagr_value:.2f}%",
        unit="percent",
        concepts=[start.concept, end.concept],
        derivation_steps=[
            f"Fetched {metric} for FY{start_year}: {start.value} ({start.concept}).",
            f"Fetched {metric} for FY{end_year}: {end.value} ({end.concept}).",
            f"Computed CAGR as (({end.value} / {start.value}) ** (1 / {periods}) - 1) * 100 = {cagr_value}.",
        ],
        citations=[_fact_citation(start), _fact_citation(end)],
    )


def ebitda(
    ticker: str,
    year: int,
    period: str = "FY",
) -> ComputedAnswer | None:
    operating_income = _resolve_fact(ticker, "operating income", year, period=period)
    depreciation = _resolve_fact(ticker, "depreciation", year, period=period)
    if operating_income is None or depreciation is None:
        return None
    value = float(operating_income.value) + float(depreciation.value)
    return ComputedAnswer(
        operation="ebitda",
        ticker=ticker.upper(),
        years=[year],
        metrics=["operating income", "depreciation"],
        value=value,
        formatted_value=_format_numeric(value, operating_income.unit),
        unit=operating_income.unit,
        concepts=[operating_income.concept, depreciation.concept],
        derivation_steps=[
            f"Fetched operating income: {operating_income.value} ({operating_income.concept}).",
            f"Fetched depreciation and amortization: {depreciation.value} ({depreciation.concept}).",
            f"Computed EBITDA as {operating_income.value} + {depreciation.value} = {value}.",
        ],
        citations=[_fact_citation(operating_income), _fact_citation(depreciation)],
    )


def ebitda_margin(
    ticker: str,
    year: int,
    period: str = "FY",
) -> ComputedAnswer | None:
    ebitda_answer = ebitda(ticker, year, period=period)
    revenue = _resolve_fact(ticker, "revenue", year, period=period)
    if ebitda_answer is None or revenue is None or float(revenue.value) == 0:
        return None
    margin = float(ebitda_answer.value) / float(revenue.value)
    return ComputedAnswer(
        operation="ebitda_margin",
        ticker=ticker.upper(),
        years=[year],
        metrics=["operating income", "depreciation", "revenue"],
        value=margin,
        formatted_value=f"{margin * 100:.2f}%",
        unit="ratio",
        concepts=ebitda_answer.concepts + [revenue.concept],
        derivation_steps=ebitda_answer.derivation_steps + [
            f"Fetched revenue: {revenue.value} ({revenue.concept}).",
            f"Computed EBITDA margin as {ebitda_answer.value} / {revenue.value} = {margin}.",
        ],
        citations=ebitda_answer.citations + [_fact_citation(revenue)],
    )


def payout_ratio(
    ticker: str,
    year: int,
) -> ComputedAnswer | None:
    dividends = _resolve_fact(ticker, "dividends", year)
    net_income = _resolve_fact(ticker, "net income", year)
    if dividends is None or net_income is None or float(net_income.value) == 0:
        return None
    ratio_value = float(dividends.value) / float(net_income.value)
    return ComputedAnswer(
        operation="payout_ratio",
        ticker=ticker.upper(),
        years=[year],
        metrics=["dividends", "net income"],
        value=ratio_value,
        formatted_value=f"{ratio_value:.4f}",
        unit="ratio",
        concepts=[dividends.concept, net_income.concept],
        derivation_steps=[
            f"Fetched dividends: {dividends.value} ({dividends.concept}).",
            f"Fetched net income: {net_income.value} ({net_income.concept}).",
            f"Computed payout ratio as {dividends.value} / {net_income.value} = {ratio_value}.",
        ],
        citations=[_fact_citation(dividends), _fact_citation(net_income)],
    )


def retention_ratio(
    ticker: str,
    year: int,
) -> ComputedAnswer | None:
    payout = payout_ratio(ticker, year)
    if payout is None:
        return None
    retention = 1.0 - float(payout.value)
    return ComputedAnswer(
        operation="retention_ratio",
        ticker=ticker.upper(),
        years=[year],
        metrics=["dividends", "net income"],
        value=retention,
        formatted_value=f"{retention:.4f}",
        unit="ratio",
        concepts=payout.concepts,
        derivation_steps=payout.derivation_steps + [
            f"Computed retention ratio as 1 - {payout.value} = {retention}.",
        ],
        citations=payout.citations,
    )


def dso(
    ticker: str,
    start_year: int,
    end_year: int,
) -> ComputedAnswer | None:
    ar_start = _resolve_fact(ticker, "accounts receivable", start_year)
    ar_end = _resolve_fact(ticker, "accounts receivable", end_year)
    revenue = _resolve_fact(ticker, "revenue", end_year)
    if ar_start is None or ar_end is None or revenue is None or float(revenue.value) == 0:
        return None
    avg_ar = (float(ar_start.value) + float(ar_end.value)) / 2.0
    days = 365.0 * avg_ar / float(revenue.value)
    return ComputedAnswer(
        operation="dso",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=["accounts receivable", "revenue"],
        value=days,
        formatted_value=f"{days:.2f}",
        unit="days",
        concepts=[ar_start.concept, ar_end.concept, revenue.concept],
        derivation_steps=[
            f"Average accounts receivable = ({ar_start.value} + {ar_end.value}) / 2 = {avg_ar}.",
            f"Revenue for FY{end_year} = {revenue.value}.",
            f"Computed DSO as 365 * {avg_ar} / {revenue.value} = {days}.",
        ],
        citations=[_fact_citation(ar_start), _fact_citation(ar_end), _fact_citation(revenue)],
    )


def dio(
    ticker: str,
    start_year: int,
    end_year: int,
) -> ComputedAnswer | None:
    inv_start = _resolve_fact(ticker, "inventory", start_year)
    inv_end = _resolve_fact(ticker, "inventory", end_year)
    cogs = _resolve_fact(ticker, "cost of goods sold", end_year)
    if inv_start is None or inv_end is None or cogs is None or float(cogs.value) == 0:
        return None
    avg_inventory = (float(inv_start.value) + float(inv_end.value)) / 2.0
    days = 365.0 * avg_inventory / float(cogs.value)
    return ComputedAnswer(
        operation="dio",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=["inventory", "cost of goods sold"],
        value=days,
        formatted_value=f"{days:.2f}",
        unit="days",
        concepts=[inv_start.concept, inv_end.concept, cogs.concept],
        derivation_steps=[
            f"Average inventory = ({inv_start.value} + {inv_end.value}) / 2 = {avg_inventory}.",
            f"COGS for FY{end_year} = {cogs.value}.",
            f"Computed DIO as 365 * {avg_inventory} / {cogs.value} = {days}.",
        ],
        citations=[_fact_citation(inv_start), _fact_citation(inv_end), _fact_citation(cogs)],
    )


def dpo(
    ticker: str,
    start_year: int,
    end_year: int,
) -> ComputedAnswer | None:
    ap_start = _resolve_fact(ticker, "accounts payable", start_year)
    ap_end = _resolve_fact(ticker, "accounts payable", end_year)
    cogs = _resolve_fact(ticker, "cost of goods sold", end_year)
    inv_start = _resolve_fact(ticker, "inventory", start_year)
    inv_end = _resolve_fact(ticker, "inventory", end_year)
    if any(fact is None for fact in (ap_start, ap_end, cogs, inv_start, inv_end)):
        return None
    denominator = float(cogs.value) + (float(inv_end.value) - float(inv_start.value))
    if denominator == 0:
        return None
    avg_ap = (float(ap_start.value) + float(ap_end.value)) / 2.0
    days = 365.0 * avg_ap / denominator
    return ComputedAnswer(
        operation="dpo",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=["accounts payable", "inventory", "cost of goods sold"],
        value=days,
        formatted_value=f"{days:.2f}",
        unit="days",
        concepts=[ap_start.concept, ap_end.concept, inv_start.concept, inv_end.concept, cogs.concept],
        derivation_steps=[
            f"Average accounts payable = ({ap_start.value} + {ap_end.value}) / 2 = {avg_ap}.",
            f"Inventory change = {inv_end.value} - {inv_start.value} = {float(inv_end.value) - float(inv_start.value)}.",
            f"Denominator = COGS + change in inventory = {cogs.value} + ({inv_end.value} - {inv_start.value}) = {denominator}.",
            f"Computed DPO as 365 * {avg_ap} / {denominator} = {days}.",
        ],
        citations=[
            _fact_citation(ap_start), _fact_citation(ap_end),
            _fact_citation(inv_start), _fact_citation(inv_end), _fact_citation(cogs),
        ],
    )


def ccc(
    ticker: str,
    start_year: int,
    end_year: int,
) -> ComputedAnswer | None:
    dio_answer = dio(ticker, start_year, end_year)
    dso_answer = dso(ticker, start_year, end_year)
    dpo_answer = dpo(ticker, start_year, end_year)
    if dio_answer is None or dso_answer is None or dpo_answer is None:
        return None
    ccc_value = float(dio_answer.value) + float(dso_answer.value) - float(dpo_answer.value)
    return ComputedAnswer(
        operation="ccc",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=["accounts payable", "accounts receivable", "inventory", "revenue", "cost of goods sold"],
        value=ccc_value,
        formatted_value=f"{ccc_value:.2f}",
        unit="days",
        concepts=dio_answer.concepts + dso_answer.concepts + dpo_answer.concepts,
        derivation_steps=dio_answer.derivation_steps + dso_answer.derivation_steps + dpo_answer.derivation_steps + [
            f"Computed CCC as DIO + DSO - DPO = {dio_answer.value} + {dso_answer.value} - {dpo_answer.value} = {ccc_value}.",
        ],
        citations=dio_answer.citations + dso_answer.citations + dpo_answer.citations,
    )


def cashflow_activity_max(
    ticker: str,
    year: int,
    period: str = "FY",
) -> ComputedAnswer | None:
    activities = [
        ("operating activities", _resolve_fact(ticker, "operating cash flow", year, period=period)),
        ("investing activities", _resolve_fact(ticker, "investing cash flow", year, period=period)),
        ("financing activities", _resolve_fact(ticker, "financing cash flow", year, period=period)),
    ]
    resolved = [(name, fact) for name, fact in activities if fact is not None]
    if not resolved:
        return None
    best_name, best_fact = max(resolved, key=lambda item: float(item[1].value))
    return ComputedAnswer(
        operation="cashflow_activity_max",
        ticker=ticker.upper(),
        years=[year],
        metrics=[name for name, _ in resolved],
        value=float(best_fact.value),
        formatted_value=f"{best_name} had the highest cash flow ({_format_numeric(float(best_fact.value), best_fact.unit)})",
        unit=best_fact.unit,
        concepts=[fact.concept for _, fact in resolved],
        derivation_steps=[
            f"{name}: {fact.value} ({fact.concept})."
            for name, fact in resolved
        ] + [
            f"Selected {best_name} because it has the highest cash flow value.",
        ],
        citations=[_fact_citation(fact) for _, fact in resolved],
    )


def ebitda_less_capex(
    ticker: str,
    year: int,
    period: str = "FY",
) -> ComputedAnswer | None:
    ebitda_answer = ebitda(ticker, year, period=period)
    capex = _resolve_fact(ticker, "capex", year, period=period)
    if ebitda_answer is None or capex is None:
        return None
    value = float(ebitda_answer.value) - abs(float(capex.value))
    return ComputedAnswer(
        operation="ebitda_less_capex",
        ticker=ticker.upper(),
        years=[year],
        metrics=["operating income", "depreciation", "capex"],
        value=value,
        formatted_value=_format_numeric(value, capex.unit),
        unit=capex.unit,
        concepts=ebitda_answer.concepts + [capex.concept],
        derivation_steps=ebitda_answer.derivation_steps + [
            f"Fetched capex: {capex.value} ({capex.concept}).",
            f"Computed EBITDA less capex as {ebitda_answer.value} - abs({capex.value}) = {value}.",
        ],
        citations=ebitda_answer.citations + [_fact_citation(capex)],
    )


def quick_ratio(ticker: str, year: int, period: str = "FY") -> ComputedAnswer | None:
    liquid_metrics = [
        "cash",
        "accounts receivable",
    ]
    numerator_value = 0.0
    concepts: list[str] = []
    citations: list[dict[str, str | int]] = []
    steps: list[str] = []
    found = False
    for metric in liquid_metrics:
        fact = _resolve_fact(ticker, metric, year, period=period)
        if fact is None:
            continue
        found = True
        numerator_value += float(fact.value)
        concepts.append(fact.concept)
        citations.append(_fact_citation(fact))
        steps.append(f"Included {metric}: {fact.value} ({fact.concept}).")
    denominator = _resolve_fact(ticker, "total current liabilities", year, period=period)
    if not found or denominator is None or float(denominator.value) == 0:
        return None
    value = numerator_value / float(denominator.value)
    return ComputedAnswer(
        operation="quick_ratio",
        ticker=ticker.upper(),
        years=[year],
        metrics=["cash", "accounts receivable", "total current liabilities"],
        value=value,
        formatted_value=f"{value:.4f}",
        unit="ratio",
        concepts=concepts + [denominator.concept],
        derivation_steps=steps + [
            f"Fetched current liabilities: {denominator.value} ({denominator.concept}).",
            f"Computed quick ratio as {numerator_value} / {denominator.value} = {value}.",
        ],
        citations=citations + [_fact_citation(denominator)],
    )


def inventory_turnover(ticker: str, start_year: int, end_year: int) -> ComputedAnswer | None:
    inv_start = _resolve_fact(ticker, "inventory", start_year)
    inv_end = _resolve_fact(ticker, "inventory", end_year)
    cogs = _resolve_fact(ticker, "cost of goods sold", end_year)
    if inv_start is None or inv_end is None or cogs is None:
        return None
    avg_inventory = (float(inv_start.value) + float(inv_end.value)) / 2.0
    if avg_inventory == 0:
        return None
    value = float(cogs.value) / avg_inventory
    return ComputedAnswer(
        operation="inventory_turnover",
        ticker=ticker.upper(),
        years=[start_year, end_year],
        metrics=["inventory", "cost of goods sold"],
        value=value,
        formatted_value=f"{value:.4f}",
        unit="ratio",
        concepts=[inv_start.concept, inv_end.concept, cogs.concept],
        derivation_steps=[
            f"Average inventory = ({inv_start.value} + {inv_end.value}) / 2 = {avg_inventory}.",
            f"Computed inventory turnover as {cogs.value} / {avg_inventory} = {value}.",
        ],
        citations=[_fact_citation(inv_start), _fact_citation(inv_end), _fact_citation(cogs)],
    )


def free_cash_flow_conversion(ticker: str, year: int) -> ComputedAnswer | None:
    fcf = compute_derived_metric(ticker, "free cash flow", year)
    net_income = _resolve_fact(ticker, "net income", year)
    if fcf is None or net_income is None or float(net_income.value) == 0:
        return None
    value = float(fcf.value) / float(net_income.value)
    return ComputedAnswer(
        operation="free_cash_flow_conversion",
        ticker=ticker.upper(),
        years=[year],
        metrics=["operating cash flow", "capex", "net income"],
        value=value,
        formatted_value=f"{value:.4f}",
        unit="ratio",
        concepts=fcf.concepts + [net_income.concept],
        derivation_steps=fcf.derivation_steps + [
            f"Fetched net income: {net_income.value} ({net_income.concept}).",
            f"Computed FCF conversion as {fcf.value} / {net_income.value} = {value}.",
        ],
        citations=fcf.citations + [_fact_citation(net_income)],
    )


def capital_intensity(ticker: str, year: int) -> ComputedAnswer | None:
    capex = _resolve_fact(ticker, "capex", year)
    revenue = _resolve_fact(ticker, "revenue", year)
    assets = _resolve_fact(ticker, "total assets", year)
    ppe = _resolve_fact(ticker, "net ppe", year)
    if any(fact is None for fact in (capex, revenue, assets, ppe)):
        return None
    capex_ratio = abs(float(capex.value)) / float(revenue.value) if float(revenue.value) else 0.0
    ppe_ratio = float(ppe.value) / float(assets.value) if float(assets.value) else 0.0
    value = capex_ratio >= 0.1 or ppe_ratio >= 0.35
    return ComputedAnswer(
        operation="capital_intensity",
        ticker=ticker.upper(),
        years=[year],
        metrics=["capex", "revenue", "net ppe", "total assets"],
        value=value,
        formatted_value="yes" if value else "no",
        unit="boolean",
        concepts=[capex.concept, revenue.concept, ppe.concept, assets.concept],
        derivation_steps=[
            f"Capex/revenue = abs({capex.value}) / {revenue.value} = {capex_ratio}.",
            f"Net PP&E / total assets = {ppe.value} / {assets.value} = {ppe_ratio}.",
            "Marked as capital intensive when capex/revenue >= 10% or net PP&E/assets >= 35%.",
        ],
        citations=[_fact_citation(capex), _fact_citation(revenue), _fact_citation(ppe), _fact_citation(assets)],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Computed / derived metrics
# ──────────────────────────────────────────────────────────────────────────────

COMPUTED_METRICS: dict[str, dict[str, str]] = {
    "gross margin": {"op": "ratio", "num": "gross profit", "den": "revenue"},
    "operating margin": {"op": "ratio", "num": "operating income", "den": "revenue"},
    "net margin": {"op": "ratio", "num": "net income", "den": "revenue"},
    "net profit margin": {"op": "ratio", "num": "net income", "den": "revenue"},
    "current ratio": {"op": "ratio", "num": "total current assets", "den": "total current liabilities"},
    "debt to equity": {"op": "ratio", "num": "total liabilities", "den": "stockholders equity"},
    "debt to equity ratio": {"op": "ratio", "num": "total liabilities", "den": "stockholders equity"},
    "free cash flow": {"op": "subtract", "a": "operating cash flow", "b": "capex"},
    "working capital": {"op": "subtract", "a": "total current assets", "b": "total current liabilities"},
    "roe": {"op": "ratio", "num": "net income", "den": "stockholders equity"},
    "return on equity": {"op": "ratio", "num": "net income", "den": "stockholders equity"},
    "roa": {"op": "ratio", "num": "net income", "den": "total assets"},
    "return on assets": {"op": "ratio", "num": "net income", "den": "total assets"},
    "asset turnover": {"op": "ratio", "num": "revenue", "den": "total assets"},
}


def compute_derived_metric(ticker: str, metric_name: str, year: int) -> ComputedAnswer | None:
    """Compute a derived financial metric from underlying XBRL facts."""
    formula = COMPUTED_METRICS.get(metric_name.lower())
    if formula is None:
        return None

    op = formula["op"]

    if op == "ratio":
        num_metric = formula["num"]
        den_metric = formula["den"]
        num_fact = _resolve_fact(ticker, num_metric, year)
        den_fact = _resolve_fact(ticker, den_metric, year)
        if num_fact is None or den_fact is None:
            return None
        if float(den_fact.value) == 0:
            return None

        ratio_val = float(num_fact.value) / float(den_fact.value)

        # Format as percentage for margins
        if "margin" in metric_name.lower() or "return on" in metric_name.lower() or metric_name.lower() in ("roe", "roa"):
            formatted = f"{ratio_val * 100:.2f}%"
        else:
            formatted = f"{ratio_val:.4f}"

        return ComputedAnswer(
            operation="derived_ratio",
            ticker=ticker.upper(),
            years=[year],
            metrics=[num_metric, den_metric],
            value=ratio_val,
            formatted_value=formatted,
            unit="ratio" if "margin" not in metric_name.lower() else "percent",
            concepts=[num_fact.concept, den_fact.concept],
            derivation_steps=[
                f"Computing {metric_name} = {num_metric} / {den_metric}.",
                f"Fetched {num_metric}: {num_fact.value} ({num_fact.concept}).",
                f"Fetched {den_metric}: {den_fact.value} ({den_fact.concept}).",
                f"Result: {num_fact.value} / {den_fact.value} = {ratio_val}.",
            ],
            citations=[_fact_citation(num_fact), _fact_citation(den_fact)],
        )

    elif op == "subtract":
        a_metric = formula["a"]
        b_metric = formula["b"]
        a_fact = _resolve_fact(ticker, a_metric, year)
        b_fact = _resolve_fact(ticker, b_metric, year)
        if a_fact is None or b_fact is None:
            return None

        result_val = float(a_fact.value) - float(b_fact.value)
        return ComputedAnswer(
            operation="derived_subtract",
            ticker=ticker.upper(),
            years=[year],
            metrics=[a_metric, b_metric],
            value=result_val,
            formatted_value=_format_numeric(result_val, a_fact.unit),
            unit=a_fact.unit,
            concepts=[a_fact.concept, b_fact.concept],
            derivation_steps=[
                f"Computing {metric_name} = {a_metric} - {b_metric}.",
                f"Fetched {a_metric}: {a_fact.value} ({a_fact.concept}).",
                f"Fetched {b_metric}: {b_fact.value} ({b_fact.concept}).",
                f"Result: {a_fact.value} - {b_fact.value} = {result_val}.",
            ],
            citations=[_fact_citation(a_fact), _fact_citation(b_fact)],
        )

    return None


def compute_xbrl_answer(plan: dict[str, Any]) -> ComputedAnswer | None:
    """Compute a deterministic answer from a simple question plan dict.

    Tries direct XBRL lookups first, then falls back to computed/derived metrics.
    """
    operation = plan["operation"]
    ticker = plan["ticker"]
    years = list(plan.get("years", []))
    period = plan.get("period", "FY")
    metrics = []
    for metric in plan.get("metrics", []):
        if metric not in metrics:
            metrics.append(metric)

    if operation == "lookup" and len(years) == 1 and metrics:
        for metric in metrics:
            if metric.lower() in COMPUTED_METRICS:
                derived = compute_derived_metric(ticker, metric, years[0])
                if derived is not None:
                    return derived
            result = direct_lookup(ticker, metric, years[0], period=period)
            if result is not None:
                return result
        if len(metrics) == 1:
            return compute_derived_metric(ticker, metrics[0], years[0])
        return None

    if operation == "absolute_change" and len(years) == 2 and len(metrics) == 1:
        return absolute_change(ticker, metrics[0], years[0], years[1])
    if operation == "percentage_change" and len(years) == 2 and len(metrics) == 1:
        return percentage_change(ticker, metrics[0], years[0], years[1])
    if operation == "cagr" and len(years) == 2 and len(metrics) == 1:
        return cagr(ticker, metrics[0], years[0], years[1])

    if operation == "ratio" and len(years) == 1 and len(metrics) == 2:
        return ratio(ticker, metrics[0], metrics[1], years[0])
    if operation == "ratio" and len(years) == 1 and len(metrics) == 1:
        # Single metric "ratio" might be a computed metric like "gross margin"
        return compute_derived_metric(ticker, metrics[0], years[0])
    if operation == "ratio_avg_balance" and len(years) == 2 and len(metrics) == 2:
        return ratio_with_average_denominator(ticker, metrics[0], metrics[1], years[0], years[1])
    if operation == "three_year_avg_ratio" and len(years) >= 3 and len(metrics) == 2:
        return three_year_average_ratio(ticker, metrics[0], metrics[1], years)
    if operation == "ebitda" and len(years) == 1:
        return ebitda(ticker, years[0], period=period)
    if operation == "ebitda_margin" and len(years) == 1:
        return ebitda_margin(ticker, years[0], period=period)
    if operation == "ebitda_less_capex" and len(years) == 1:
        return ebitda_less_capex(ticker, years[0], period=period)
    if operation == "payout_ratio" and len(years) == 1:
        return payout_ratio(ticker, years[0])
    if operation == "retention_ratio" and len(years) == 1:
        return retention_ratio(ticker, years[0])
    if operation == "quick_ratio" and len(years) == 1:
        return quick_ratio(ticker, years[0], period=period)
    if operation == "free_cash_flow_conversion" and len(years) == 1:
        return free_cash_flow_conversion(ticker, years[0])
    if operation == "capital_intensity" and len(years) == 1:
        return capital_intensity(ticker, years[0])
    if operation == "dso" and len(years) == 2:
        return dso(ticker, years[0], years[1])
    if operation == "dio" and len(years) == 2:
        return dio(ticker, years[0], years[1])
    if operation == "dpo" and len(years) == 2:
        return dpo(ticker, years[0], years[1])
    if operation == "ccc" and len(years) == 2:
        return ccc(ticker, years[0], years[1])
    if operation == "inventory_turnover" and len(years) == 2:
        return inventory_turnover(ticker, years[0], years[1])
    if operation == "cashflow_activity_max" and len(years) == 1:
        return cashflow_activity_max(ticker, years[0], period=period)

    if operation == "compare" and years and len(metrics) == 1:
        return compare_years(ticker, metrics[0], years)
    if operation == "existence" and len(years) == 1 and len(metrics) == 1:
        return metric_exists(ticker, metrics[0], years[0])
    return None
