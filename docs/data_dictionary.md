# Data Dictionary

## Purpose
Every field in this database is documented here: what it measures, where it comes from, how we handle inconsistencies, and what confidence level we assign.

This document serves two purposes:
1. **Internal rigor** — Forces us to confront every assumption
2. **External credibility** — A recruiter or professor can verify our methodology

---

## Key Concepts

### Fiscal Year Convention
Most Ivy endowments report on a fiscal year ending **June 30**. When we say "FY2023," we mean the period July 1, 2022 through June 30, 2023.

**Exceptions:**
- Stanford: August 31 fiscal year end
- Northwestern: August 31 fiscal year end
- UT System: August 31 fiscal year end
- Texas A&M: August 31 fiscal year end

**Implication:** When comparing FY2008 crisis performance, Stanford's numbers include two extra months of the crash vs. June-ending peers. We note this wherever it affects analysis.

### Confidence Levels
- **high** — Directly reported in audited financial statements or 990 filings
- **medium** — Triangulated from multiple sources, or reported in non-audited materials (CIO letters, news)
- **low** — Estimated/inferred from peer comparisons, return patterns, or industry benchmarks

### Source Priority (when sources conflict)
1. Audited financial statements (highest authority)
2. University investment office annual reports
3. IRS Form 990
4. NACUBO survey data
5. News coverage / CIO speeches

---

## Table: endowment_annual

| Field | Definition | Unit | Source | Notes |
|-------|-----------|------|--------|-------|
| endowment_value_millions | Total market value of pooled endowment at fiscal year end | USD millions | Audited financials (primary), 990 total assets (secondary) | 990 "total assets" includes non-endowment assets; always prefer audited financial statement figure. Difference is typically 5-15%. |
| annual_return_pct | Total investment return for the fiscal year | Percentage | Investment reports (primary), financials (secondary) | Net of investment management fees unless noted. Gross vs. net distinction matters ~1-2% per year. Not all institutions clarify. |
| return_net_of_fees | Whether the reported return is net (1) or gross (0) of fees | Binary | Report methodology sections | If unknown, assume net — most report net. Flag in notes. |
| spending_millions | Total endowment distribution to university operating budget | USD millions | Audited financials | Includes restricted and unrestricted distributions. |
| spending_rate_pct | Annual payout as percentage of endowment value | Percentage | Calculated or reported | Different institutions calculate the denominator differently (beginning value, average, trailing 12-quarter average). We standardize to: spending / beginning-of-year value. |
| spending_as_pct_of_budget | Endowment spending divided by total operating expenses | Percentage | Audited financials | Shows dependence on endowment. Yale ~30%, Columbia ~15-20%. Higher ratio = more endowment-dependent = different risk tolerance. |
| new_gifts_millions | New contributions to endowment (gifts + transfers in) | USD millions | Audited financials, 990 | Critical for separating investment performance from fundraising. Value growth = returns + gifts - spending. |
| real_return_pct | Nominal return minus CPI inflation | Percentage | Calculated | Uses annual CPI from Bureau of Labor Statistics. Aligns to fiscal year (July-June CPI change). |
| endowment_per_student | Endowment value divided by full-time equivalent students | USD | Calculated | Uses approximate FTE from institution metadata. Updated periodically, not annually — introduces small error. |
| growth_rate_yoy_pct | Year-over-year change in total endowment value | Percentage | Calculated | Combines investment returns + gifts - spending. Not the same as investment return. |
| data_quality_score | Overall confidence in this year's data for this institution | 1-5 scale | Our assessment | 5 = all values from audited sources, reconciled. 1 = mostly inferred. |

## Table: asset_allocation

| Field | Definition | Notes |
|-------|-----------|-------|
| reported_category | Exact category name from the institution's own reporting | Kept verbatim to preserve provenance. Examples: Yale reports "Absolute Return"; Harvard reports "Hedge Funds"; Brown reports "Alternatives." |
| reported_pct | Percentage allocation as reported | Should sum to ~100% per institution per year. |
| taxonomy_id | Our standardized category mapping | Maps institution-specific names to common taxonomy. This is where the analytical work happens. |
| confidence | How sure we are about this allocation point | 'high' if directly reported with that breakdown. 'medium' if we split a broader bucket using inference. 'low' if estimated from return patterns or peers. |
| inference_method | How we estimated (if not directly reported) | Examples: "Split Brown's 55% alternatives into PE/HF using return correlation with Yale's known splits" or "Inferred from FY2021 strong outperformance aligning with PE exit year." |

### Asset Class Mapping Challenges

The central data problem of this project: institutions use different taxonomies.

**Example — what "alternatives" means:**

| Institution | Their Label | What's Likely Included |
|------------|-------------|----------------------|
| Yale | Venture Capital (23.5%), Leveraged Buyouts (17.5%), Absolute Return (14.5%) | Fully disaggregated — gold standard |
| Harvard | Private Equity (34%), Hedge Funds (32%), Real Estate (5%) | Good breakdown |
| Brown | "Alternative Investments" (58%) | PE + HF + Real Assets in one bucket |
| Williams | "Marketable Alternatives" + "Private Equity & Venture Capital" | Partial breakdown |

**Our approach:**
1. Map every institution's labels to our taxonomy
2. For vague buckets ("alternatives"), create `alt_undifferentiated` entries with the total
3. If we can infer sub-allocations (from returns, news, or CIO commentary), create separate entries with `confidence = 'medium'` or `'low'` and document the inference method
4. Never present inferred allocations without flagging them

## Table: leadership

| Field | Definition | Notes |
|-------|-----------|-------|
| compensation_total | Total compensation from 990 (salary + bonus + deferred + other) | 990 reports prior-year comp. Timing varies. Some institutions report CIO under management company, others under university. |
| prior_firm_type | Category of the CIO's background before joining | Hypothesis: CIO background predicts allocation bias (ex-VC CIO → heavier VC allocation). |

## Table: crisis_events

| Field | Definition | Notes |
|-------|-----------|-------|
| drawdown_pct | Maximum peak-to-trough decline in endowment value | Measured from highest point before crisis to lowest point during. For annual-only data, this understates the true intra-year drawdown. |
| recovery_quarters | Quarters from trough back to prior peak value | In nominal terms. Real recovery (inflation-adjusted) takes longer. |
| forced_actions | Actions taken under duress during the crisis | 2008 examples: Harvard drew $2.5B credit line, sold PE stakes on secondary market, froze construction. These are revealed-preference data points about liquidity management. |

## Table: benchmarks

Standard comparison points stored per fiscal year:

| Benchmark | Definition | Source |
|-----------|-----------|--------|
| sp500 | S&P 500 total return (dividends reinvested) | Bloomberg, Yahoo Finance |
| 60_40 | 60% S&P 500 / 40% Bloomberg US Aggregate Bond Index | Calculated |
| nacubo_large | NACUBO average for endowments >$1B | NACUBO-TIAA annual study |
| nacubo_all | NACUBO average for all participating endowments | NACUBO-TIAA annual study |
| cpi | Consumer Price Index annual change (June-June) | Bureau of Labor Statistics |
| yale_model_proxy | Proxy for "ideal" Yale Model allocation returns | Constructed benchmark using target weights |

---

## Reconciliation Notes

Common discrepancies and how we resolve them:

**990 total assets vs. audited endowment value:** 990 includes all university assets (buildings, receivables, etc.), not just endowment. Always use audited financial statement for endowment value. 990 is a backup/cross-check only.

**NACUBO reported returns vs. university reported returns:** Occasionally differ by 0.1-0.5% due to rounding, timing, or methodology differences. Use the university's own audited figure; note the NACUBO figure as a cross-check.

**Fiscal year timing for public universities:** Texas institutions (Aug 31 FY end) see different market conditions than June 30 peers in the same "fiscal year." We align by fiscal year label but flag the timing difference in regime-specific analysis.

**Pre-2005 data quality:** 990 digital records get spottier before 2005. Some institutions' early-2000s data may need manual extraction from PDF 990s. Flag any manually extracted values.
