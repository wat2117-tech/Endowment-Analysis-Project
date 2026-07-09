"""
Data Validation & Reconciliation
=================================
Runs integrity checks on the endowment database.
Flags discrepancies between sources, missing data, and outliers.

Run after loading data:
    python validate.py              # Full validation report
    python validate.py --fix        # Auto-fix where possible
    python validate.py --institution yale  # Check one institution
"""

import sqlite3
import os
import sys
import argparse
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'endowments.db')

# Thresholds
RETURN_OUTLIER_LOW = -40.0      # Flag returns below -40%
RETURN_OUTLIER_HIGH = 60.0      # Flag returns above +60%
SOURCE_RECONCILE_THRESHOLD = 5.0  # Flag if two sources differ by >5%
EXPECTED_YEARS = list(range(2000, 2025))


class ValidationReport:
    def __init__(self):
        self.errors = []     # Must fix
        self.warnings = []   # Should investigate
        self.info = []       # Nice to know
        self.stats = {}

    def error(self, institution, message):
        self.errors.append((institution, message))

    def warning(self, institution, message):
        self.warnings.append((institution, message))

    def log(self, institution, message):
        self.info.append((institution, message))

    def print_report(self):
        print("\n" + "=" * 70)
        print("DATA VALIDATION REPORT")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 70)

        if self.errors:
            print(f"\n🔴 ERRORS ({len(self.errors)}) — Must Fix")
            print("-" * 50)
            for inst, msg in self.errors:
                print(f"  [{inst}] {msg}")

        if self.warnings:
            print(f"\n🟡 WARNINGS ({len(self.warnings)}) — Investigate")
            print("-" * 50)
            for inst, msg in self.warnings:
                print(f"  [{inst}] {msg}")

        if self.info:
            print(f"\n🔵 INFO ({len(self.info)})")
            print("-" * 50)
            for inst, msg in self.info:
                print(f"  [{inst}] {msg}")

        if self.stats:
            print(f"\n📊 COVERAGE STATS")
            print("-" * 50)
            for key, val in self.stats.items():
                print(f"  {key}: {val}")

        total = len(self.errors) + len(self.warnings)
        if total == 0:
            print("\n✅ All checks passed!")
        else:
            print(f"\nTotal issues: {len(self.errors)} errors, {len(self.warnings)} warnings")


def check_coverage(conn, report, institution_id=None):
    """Check which institution-years have data and which are missing."""
    cursor = conn.cursor()

    where = f"WHERE i.id = '{institution_id}'" if institution_id else ""
    cursor.execute(f"""
        SELECT i.id, i.short_name, i.tier,
               GROUP_CONCAT(e.fiscal_year) as years_present,
               COUNT(e.fiscal_year) as year_count
        FROM institutions i
        LEFT JOIN endowment_annual e ON i.id = e.institution_id
        {where}
        GROUP BY i.id
        ORDER BY i.tier, i.short_name
    """)

    total_possible = 0
    total_present = 0

    for inst_id, name, tier, years_str, count in cursor.fetchall():
        years_present = set()
        if years_str:
            years_present = set(int(y) for y in years_str.split(','))

        missing = [y for y in EXPECTED_YEARS if y not in years_present]

        total_possible += len(EXPECTED_YEARS)
        total_present += count

        if len(missing) > 10:
            report.error(name, f"Missing {len(missing)}/24 years of data: {missing[:5]}...")
        elif len(missing) > 5:
            report.warning(name, f"Missing {len(missing)} years: {missing}")
        elif len(missing) > 0:
            report.log(name, f"Missing {len(missing)} years: {missing}")
        else:
            report.log(name, "Complete coverage 2000-2024")

    report.stats['Data coverage'] = f"{total_present}/{total_possible} institution-years ({100*total_present/max(total_possible,1):.0f}%)"


def check_return_outliers(conn, report, institution_id=None):
    """Flag suspicious return values."""
    cursor = conn.cursor()

    where = f"AND e.institution_id = '{institution_id}'" if institution_id else ""
    cursor.execute(f"""
        SELECT i.short_name, e.fiscal_year, e.annual_return_pct
        FROM endowment_annual e
        JOIN institutions i ON e.institution_id = i.id
        WHERE e.annual_return_pct IS NOT NULL {where}
        ORDER BY e.annual_return_pct
    """)

    for name, year, ret in cursor.fetchall():
        if ret < RETURN_OUTLIER_LOW:
            report.warning(name, f"FY{year}: Return of {ret:.1f}% is extremely low — verify source")
        elif ret > RETURN_OUTLIER_HIGH:
            report.warning(name, f"FY{year}: Return of {ret:.1f}% is extremely high — verify source")


def check_value_continuity(conn, report, institution_id=None):
    """Check for implausible year-over-year endowment value changes."""
    cursor = conn.cursor()

    where = f"AND e.institution_id = '{institution_id}'" if institution_id else ""
    cursor.execute(f"""
        SELECT i.short_name, e.fiscal_year,
               e.endowment_value_millions,
               LAG(e.endowment_value_millions) OVER (
                   PARTITION BY e.institution_id ORDER BY e.fiscal_year
               ) as prev_value
        FROM endowment_annual e
        JOIN institutions i ON e.institution_id = i.id
        WHERE e.endowment_value_millions IS NOT NULL {where}
        ORDER BY e.institution_id, e.fiscal_year
    """)

    for name, year, value, prev_value in cursor.fetchall():
        if prev_value and prev_value > 0:
            change_pct = ((value - prev_value) / prev_value) * 100

            # Endowment shouldn't change by more than ~50% in a year
            # (even 2008 was about -25%, and 2021 was about +40%)
            if abs(change_pct) > 50:
                report.warning(name, f"FY{year}: Value changed {change_pct:+.1f}% (${prev_value:,.0f}M → ${value:,.0f}M) — verify")


def check_allocation_sums(conn, report, institution_id=None):
    """Check that asset allocation percentages sum to ~100%."""
    cursor = conn.cursor()

    where = f"AND a.institution_id = '{institution_id}'" if institution_id else ""
    cursor.execute(f"""
        SELECT i.short_name, a.fiscal_year, SUM(a.reported_pct) as total_pct
        FROM asset_allocation a
        JOIN institutions i ON a.institution_id = i.id
        WHERE a.reported_pct IS NOT NULL {where}
        GROUP BY a.institution_id, a.fiscal_year
        HAVING ABS(SUM(a.reported_pct) - 100) > 2
    """)

    for name, year, total in cursor.fetchall():
        report.warning(name, f"FY{year}: Asset allocation sums to {total:.1f}% (should be ~100%)")


def check_spending_rate(conn, report, institution_id=None):
    """Flag spending rates outside normal range (3-7%)."""
    cursor = conn.cursor()

    where = f"AND e.institution_id = '{institution_id}'" if institution_id else ""
    cursor.execute(f"""
        SELECT i.short_name, e.fiscal_year, e.spending_rate_pct
        FROM endowment_annual e
        JOIN institutions i ON e.institution_id = i.id
        WHERE e.spending_rate_pct IS NOT NULL {where}
    """)

    for name, year, rate in cursor.fetchall():
        if rate < 3.0 or rate > 7.0:
            report.warning(name, f"FY{year}: Spending rate {rate:.1f}% outside typical 3-7% range")


def check_source_provenance(conn, report, institution_id=None):
    """Check that key data points have source attribution."""
    cursor = conn.cursor()

    where = f"AND e.institution_id = '{institution_id}'" if institution_id else ""

    # Check how many data points lack source references
    cursor.execute(f"""
        SELECT i.short_name,
               COUNT(*) as total_rows,
               SUM(CASE WHEN e.endowment_value_source_id IS NULL AND e.endowment_value_millions IS NOT NULL THEN 1 ELSE 0 END) as value_no_source,
               SUM(CASE WHEN e.return_source_id IS NULL AND e.annual_return_pct IS NOT NULL THEN 1 ELSE 0 END) as return_no_source
        FROM endowment_annual e
        JOIN institutions i ON e.institution_id = i.id
        WHERE 1=1 {where}
        GROUP BY i.id
    """)

    for name, total, val_missing, ret_missing in cursor.fetchall():
        if val_missing and val_missing > 0:
            report.warning(name, f"{val_missing}/{total} endowment values have no source attribution")
        if ret_missing and ret_missing > 0:
            report.warning(name, f"{ret_missing}/{total} return values have no source attribution")


def check_confidence_distribution(conn, report):
    """Report on data confidence levels across the dataset."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            e.endowment_value_confidence,
            COUNT(*)
        FROM endowment_annual e
        WHERE e.endowment_value_millions IS NOT NULL
        GROUP BY e.endowment_value_confidence
    """)

    for conf, count in cursor.fetchall():
        report.stats[f'Endowment values ({conf} confidence)'] = count

    cursor.execute("""
        SELECT a.confidence, COUNT(*)
        FROM asset_allocation a
        GROUP BY a.confidence
    """)

    for conf, count in cursor.fetchall():
        report.stats[f'Allocation data ({conf} confidence)'] = count


def compute_derived_fields(conn, report):
    """Calculate derived fields (real returns, per-student, YoY growth)."""
    cursor = conn.cursor()

    # Get CPI data from benchmarks table (if loaded)
    cursor.execute("""
        SELECT fiscal_year, return_pct FROM benchmarks
        WHERE benchmark_name = 'cpi'
    """)
    cpi = {row[0]: row[1] for row in cursor.fetchall()}

    # Calculate per-student values
    cursor.execute("""
        UPDATE endowment_annual
        SET endowment_per_student = endowment_value_millions * 1000000.0 / (
            SELECT student_count_approx FROM institutions
            WHERE institutions.id = endowment_annual.institution_id
        )
        WHERE endowment_value_millions IS NOT NULL
    """)

    # Calculate YoY growth
    cursor.execute("""
        SELECT e.institution_id, e.fiscal_year, e.endowment_value_millions
        FROM endowment_annual e
        WHERE e.endowment_value_millions IS NOT NULL
        ORDER BY e.institution_id, e.fiscal_year
    """)

    prev = {}
    updates = []
    for inst, year, value in cursor.fetchall():
        if inst in prev:
            prev_val = prev[inst]
            if prev_val > 0:
                growth = ((value - prev_val) / prev_val) * 100
                updates.append((growth, inst, year))
        prev[inst] = value

    cursor.executemany("""
        UPDATE endowment_annual SET growth_rate_yoy_pct = ?
        WHERE institution_id = ? AND fiscal_year = ?
    """, updates)

    conn.commit()
    report.log('ALL', f'Computed {len(updates)} YoY growth rates')


def generate_data_quality_matrix(conn, report):
    """Generate the data confidence matrix for the project deck."""
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("DATA CONFIDENCE MATRIX")
    print("=" * 70)
    print(f"\n{'Institution':<15} {'Years':<8} {'Values':<8} {'Returns':<9} {'Alloc':<8} {'Sources':<8} {'Score'}")
    print("-" * 70)

    cursor.execute("""
        SELECT
            i.short_name,
            i.tier,
            COUNT(e.fiscal_year) as years,
            SUM(CASE WHEN e.endowment_value_millions IS NOT NULL THEN 1 ELSE 0 END) as has_value,
            SUM(CASE WHEN e.annual_return_pct IS NOT NULL THEN 1 ELSE 0 END) as has_return,
            (SELECT COUNT(*) FROM asset_allocation a WHERE a.institution_id = i.id) as alloc_points,
            (SELECT COUNT(*) FROM sources s WHERE s.institution_id = i.id) as source_count
        FROM institutions i
        LEFT JOIN endowment_annual e ON i.id = e.institution_id
        GROUP BY i.id
        ORDER BY i.tier, i.short_name
    """)

    for name, tier, years, values, returns, alloc, sources in cursor.fetchall():
        # Simple quality score: weight by completeness
        max_years = 24
        score = (
            (min(values or 0, max_years) / max_years) * 30 +     # Value completeness
            (min(returns or 0, max_years) / max_years) * 30 +    # Return completeness
            (min(alloc or 0, max_years) / max_years) * 20 +      # Allocation data
            (min(sources or 0, 50) / 50) * 20                     # Source documentation
        )

        print(f"{name:<15} {years or 0:<8} {values or 0:<8} {returns or 0:<9} {alloc or 0:<8} {sources or 0:<8} {score:.0f}/100")


def main():
    parser = argparse.ArgumentParser(description='Validate endowment database')
    parser.add_argument('--institution', type=str, help='Check specific institution')
    parser.add_argument('--fix', action='store_true', help='Auto-compute derived fields')
    parser.add_argument('--matrix', action='store_true', help='Generate data quality matrix')
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Run schema.py first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    report = ValidationReport()

    # Run all checks
    check_coverage(conn, report, args.institution)
    check_return_outliers(conn, report, args.institution)
    check_value_continuity(conn, report, args.institution)
    check_allocation_sums(conn, report, args.institution)
    check_spending_rate(conn, report, args.institution)
    check_source_provenance(conn, report, args.institution)
    check_confidence_distribution(conn, report)

    if args.fix:
        compute_derived_fields(conn, report)

    report.print_report()

    if args.matrix:
        generate_data_quality_matrix(conn, report)

    conn.close()


if __name__ == '__main__':
    main()
