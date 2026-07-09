# CLAUDE.md

## Project Overview
This is an Ivy+ Endowment Performance Analysis tracking 24 university endowments from 2000–2024. The goal is to rank endowments by risk-adjusted performance, explain why returns diverged, and predict which are best positioned for 2025–2030. This is a recruiting portfolio piece for finance/consulting — it needs to demonstrate analytical rigor, not just data collection.

## Institutions (24 total)
- **Ivy League (8):** Harvard, Yale, Princeton, Penn, Columbia, Cornell, Dartmouth, Brown
- **Elite Privates (6):** Stanford, MIT, Duke, UChicago, Northwestern, Rice
- **Major Publics (5):** UT System, Texas A&M, Michigan, UVA, Berkeley
- **Liberal Arts (5):** Williams, Amherst, Pomona, Grinnell, Swarthmore

Selection rationale is in `docs/institutions.md`. Each institution is included for a specific analytical reason (scale comparison, governance comparison, OCIO vs internal management, etc.).

## Architecture
- **Database:** SQLite at `data/endowments.db`. Schema defined in `scripts/schema.py`. Normalized tables: `institutions`, `endowment_annual`, `asset_allocation`, `leadership`, `crisis_events`, `events`, `holdings_13f`, `benchmarks`, `reconciliation_log`, `sources`, `governance`, `asset_class_taxonomy`.
- **Every data point must link to a source record** in the `sources` table. No orphaned numbers.
- **Confidence levels** (`high`, `medium`, `low`) are tracked on all values. `high` = audited financials. `medium` = triangulated/inferred. `low` = rough estimate.
- **Asset class taxonomy** in `asset_class_taxonomy` maps inconsistent institutional reporting to 25 standardized categories. When an institution reports "alternatives" as one bucket, use `alt_undifferentiated` and document.

## Key Files
```
scripts/
  schema.py          — Initialize DB with tables + seed data (24 institutions, 25 asset classes)
  collect_990.py     — Pull IRS 990 data from ProPublica API (needs `requests`)
  enter_data.py      — Manual data entry + CSV bulk import + template generation
  validate.py        — Data quality checks, coverage gaps, outlier detection, quality matrix

docs/
  institutions.md    — Why each institution is included
  data_dictionary.md — Every field defined with sources, confidence rules, reconciliation notes

data/
  endowments.db      — SQLite database
  raw/               — Downloaded source files (990 JSONs, PDFs)
  processed/         — Cleaned CSVs, entry templates
  sources/           — Annual reports, financial statements
```

## Data Sources (priority order)
1. University audited financial statements (treasurer/CFO websites) — primary for endowment value, returns, spending
2. IRS Form 990 (ProPublica API, EIN lookup) — compensation data, total assets cross-check
3. NACUBO-TIAA Study of Endowments — peer benchmarks, industry averages
4. SEC Form 13F (EDGAR) — public equity holdings only, <20% of most endowments
5. University investment office annual reports — asset allocation, CIO commentary
6. News/academic papers — qualitative context, strategy shifts

Public universities (UT, Texas A&M, Berkeley) don't file 990s. Use state financial reports and public records instead.

## Fiscal Year Convention
Most institutions end June 30. Exceptions: Stanford, Northwestern, UT System, Texas A&M end August 31. When comparing crisis periods (especially 2008), the 2-month difference matters — flag it.

## What Needs to Be Built Next

### Phase 1: Data Population (current priority)
- Scrape/collect endowment values and annual returns for all 24 institutions, 2000–2024
- Start with the most transparent institutions (Yale, Harvard, MIT, Princeton, public universities)
- Fill in the CSV template (`data/processed/entry_template.csv`) or write additional scrapers
- For each data point entered, create a corresponding `sources` record
- Run `validate.py --matrix` frequently to track coverage

### Phase 2: Quantitative Analysis
- Calculate risk-adjusted metrics: Sharpe ratio, Sortino ratio, max drawdown, recovery periods
- Build composite ranking methodology (weight: returns 30%, risk-adjusted 30%, drawdown recovery 15%, allocation evolution 15%, governance 10%)
- Regime-specific analysis: how did each endowment perform during dot-com (2000–02), GFC (2008–09), COVID (2020), rate shock (2022–23)?
- Benchmark comparisons: S&P 500, 60/40, NACUBO peer averages, CPI-adjusted real returns

### Phase 3: Qualitative Layer
- Map CIO tenures to performance periods (is there a correlation?)
- Document major strategy shifts, divestment decisions, structural changes
- Crisis forensics: who was forced to sell at the bottom in 2008? Who had liquidity buffers?
- OCIO vs internal management performance comparison (LACs vs large endowments)

### Phase 4: Forward-Looking Thesis
- Which endowments are positioned for higher rates (less PE/VC heavy)?
- Who has AI/tech exposure through VC allocations?
- Donor base demographics and future fundraising capacity
- CIO succession risk

### Phase 5: Deliverables
- 15–20 slide deck with methodology, rankings, key findings
- 1-page executive summary with top 3 contrarian insights
- Interactive dashboard (Plotly/Streamlit/Tableau) with filters for time period, institution, metric
- Data confidence matrix showing what we know vs. inferred

## Code Standards
- Python 3.8+. Only external dependency is `requests`.
- All database operations go through SQLite. No separate database server.
- Every script should be runnable independently with `python scripts/filename.py`.
- Use argparse for CLI flags. Scripts should work with no arguments (sensible defaults) and support `--institution` and `--year` filters where applicable.
- Print clear progress output. No silent failures.
- When writing new scrapers or data collection scripts, always create `sources` records for provenance.

## Common Queries You'll Need

```sql
-- Check data coverage
SELECT i.short_name, i.tier, COUNT(e.fiscal_year) as years,
       SUM(CASE WHEN e.endowment_value_millions IS NOT NULL THEN 1 ELSE 0 END) as has_value,
       SUM(CASE WHEN e.annual_return_pct IS NOT NULL THEN 1 ELSE 0 END) as has_return
FROM institutions i
LEFT JOIN endowment_annual e ON i.id = e.institution_id
GROUP BY i.id ORDER BY i.tier, i.short_name;

-- Performance comparison for a specific year
SELECT i.short_name, i.tier, e.endowment_value_millions, e.annual_return_pct, e.spending_rate_pct
FROM endowment_annual e
JOIN institutions i ON e.institution_id = i.id
WHERE e.fiscal_year = 2023
ORDER BY e.annual_return_pct DESC;

-- Asset allocation for an institution over time
SELECT fiscal_year, reported_category, reported_pct, confidence
FROM asset_allocation
WHERE institution_id = 'yale'
ORDER BY fiscal_year, reported_category;

-- CIO tenure vs performance
SELECT * FROM v_cio_performance;

-- Find data gaps
SELECT i.short_name, i.tier FROM institutions i
WHERE i.id NOT IN (
    SELECT DISTINCT institution_id FROM endowment_annual WHERE fiscal_year = 2023
);
```

## Important Constraints
- 990 "total assets" ≠ endowment value. Always prefer audited financial statements. The difference is typically 5–15%.
- Returns may be gross or net of fees. Track which in `return_net_of_fees`. Assume net unless clearly stated otherwise.
- Asset allocation categories are inconsistent across institutions. That's the central data challenge. See `docs/data_dictionary.md` for mapping approach.
- Don't fabricate data. If a value isn't available, leave it NULL and note why. Inferred values get `confidence = 'medium'` or `'low'` with the method documented.
