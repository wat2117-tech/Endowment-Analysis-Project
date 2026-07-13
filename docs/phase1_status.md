# Phase 1 Status — Data Population

*Last updated: 2026-07-10*

## Coverage: 443/600 institution-years (74%)

- **Complete 2000–2024 (values):** Yale, Harvard, Princeton, MIT, Stanford, Penn, Columbia, Cornell
- **Substantial (17–19 yrs):** Brown, Dartmouth, Duke, UChicago, Northwestern, Rice, Michigan, Amherst, Williams, Pomona, Grinnell
- **Partial (9–11 yrs):** Swarthmore, UVA, UT System, Texas A&M
- **Thin (4 yrs):** Berkeley — entity-definition problem (UC pools most endowment centrally; campus-attributed totals need careful primary-source work)

## Confidence breakdown (endowment values)

- `medium` (319): compiled from investment-office announcements and NACUBO
  study tables; each row has a `sources` record naming the document to verify against
- `low` (91): rough recall of NACUBO tables (±10%); explicitly marked
  "upgrade via primary source" in notes
- `high` (0): **nothing is verified against audited financials yet** — that
  is the main remaining Phase 1 task

## Returns coverage

Full or near-full return series: Yale, Harvard (2000–2024), Princeton, MIT,
Stanford, Penn, Columbia (2009–2024), Brown (2015–2024). Crisis-year (2009)
returns captured for 12 institutions. Most NACUBO-anchor years are value-only;
returns marked "pending primary source."

## Cross-check data

IRS 990 filings (ProPublica JSON) saved under `data/raw/990s/` for all 21
private institutions, ~12–13 filings each. Remember: 990 total assets ≠
endowment value (5–15% difference typical).

## Corrections log

- Dartmouth FY2009: batch 2 entered $3,660M (the FY2008 figure); corrected
  to ~$2,825M in batch 3 (consistent with the −19.6% GFC return).
- EINs fixed in schema.py + DB: Amherst 04-2103542, Williams 04-2104847,
  Pomona 95-1664112 (previous values returned ProPublica API errors).

## Missing-data policy

Remaining gaps are **flagged, not filled** (see `docs/uncertainty.md`).
Inaccessible information — unpublished LAC returns, archival NACUBO tables,
Berkeley's entity ambiguity — stays NULL with a documented reason. Working
transparently with uncertainty is part of the project's methodology; the
gap inventory below is a record of what is *knowable*, not a to-do list to
force to 100%.

## Remaining Phase 1 work

1. **Verify against primary documents** — download audited financial
   statements and investment-office reports, upgrade rows to `high`,
   record in `reconciliation_log`. Priority: any figure feeding Phase 2
   metrics (returns, crisis-year values).
2. **Berkeley** — resolve entity definition (UCB Foundation vs. regental
   share) before adding more years.
3. **Fill 2001–2006** for the non-HYP privates and LACs (needs archived
   NACUBO tables or university archives).
4. **Return series** for publics (UTIMCO/UVIMCO/Michigan publish these in
   annual reports — scrapeable) and LACs.
5. Spending rates, gifts, and asset-allocation tables (separate collection
   pass; `asset_allocation` is still empty).
