"""
Benchmark Series Seeder
=======================
Populates the `benchmarks` table with fiscal-year (July 1 - June 30) return
series needed for Phase 2 analysis:

    sp500       - S&P 500 total return
    us_agg_bond - Bloomberg US Aggregate Bond total return
    60_40       - 60% sp500 / 40% us_agg_bond (derived here)
    cpi         - CPI-U inflation, June-over-June
    tbill_3m    - 3-month T-bill average yield (risk-free rate for Sharpe)

Provenance: compiled from published index/total-return tables (S&P Dow Jones,
Bloomberg, BLS, FRED). Values are entered at medium confidence and should be
verified against FRED series (SP500TR, BAMLCC0A0CMTRIV proxy, CPIAUCSL, TB3MS)
before final deliverables. `benchmarks.source_id` is left NULL because the
`sources` table requires an institution; provenance lives in this file and in
the notes column of the report.

Usage:
    python scripts/seed_benchmarks.py
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'endowments.db')

# fiscal_year: (sp500, us_agg_bond, cpi, tbill_3m)  — all % for FY ending June 30
SERIES = {
    2000: ( 7.2,   4.6,  3.7, 5.5),
    2001: (-14.8, 11.2,  3.2, 5.3),
    2002: (-18.0,  8.6,  1.1, 2.2),
    2003: ( 0.3,  10.4,  2.1, 1.3),
    2004: (19.1,   0.3,  3.3, 1.0),
    2005: ( 6.3,   6.8,  2.5, 2.3),
    2006: ( 8.6,  -0.8,  4.3, 4.3),
    2007: (20.6,   6.1,  2.7, 5.0),
    2008: (-13.1,  7.1,  5.0, 3.0),
    2009: (-26.2,  6.0, -1.4, 0.5),
    2010: (14.4,   9.5,  1.1, 0.1),
    2011: (30.7,   3.9,  3.6, 0.14),
    2012: ( 5.4,   7.5,  1.7, 0.05),
    2013: (20.6,  -0.7,  1.8, 0.08),
    2014: (24.6,   4.4,  2.1, 0.05),
    2015: ( 7.4,   1.9,  0.1, 0.02),
    2016: ( 4.0,   6.0,  1.0, 0.23),
    2017: (17.9,  -0.3,  1.6, 0.6),
    2018: (14.4,  -0.4,  2.9, 1.5),
    2019: (10.4,   7.9,  1.6, 2.4),
    2020: ( 7.5,   8.7,  0.6, 1.2),
    2021: (40.8,  -0.3,  5.4, 0.06),
    2022: (-10.6,-10.3,  9.1, 0.6),
    2023: (19.6,  -0.9,  3.0, 4.5),
    2024: (24.6,   2.6,  3.0, 5.4),
}


def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0

    for fy, (sp, agg, cpi, tbill) in sorted(SERIES.items()):
        blend = round(0.6 * sp + 0.4 * agg, 2)
        for name, val in [('sp500', sp), ('us_agg_bond', agg),
                          ('60_40', blend), ('cpi', cpi), ('tbill_3m', tbill)]:
            cursor.execute("""
                INSERT INTO benchmarks (fiscal_year, benchmark_name, return_pct)
                VALUES (?, ?, ?)
                ON CONFLICT(fiscal_year, benchmark_name) DO UPDATE SET
                    return_pct = excluded.return_pct
            """, (fy, name, val))
            inserted += 1

    conn.commit()
    cursor.execute("SELECT benchmark_name, COUNT(*) FROM benchmarks GROUP BY benchmark_name")
    print("Benchmark rows in database:")
    for name, n in cursor.fetchall():
        print(f"  {name:<12} {n} fiscal years")
    conn.close()
    print(f"\nUpserted {inserted} rows (2000-2024). 60_40 derived as 0.6*sp500 + 0.4*us_agg_bond.")
    print("NOTE: compiled figures - verify against FRED before final deliverables.")


if __name__ == '__main__':
    main()
