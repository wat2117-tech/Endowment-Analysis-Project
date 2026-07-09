"""
Manual Data Entry Helper
=========================
Interactive tool for entering data from audited financial statements,
investment reports, and other sources that can't be scraped automatically.

This is where most of the actual data will come from — the 990 scraper
gives you a skeleton, but audited financials are the primary source for
endowment values, returns, and spending.

Usage:
    python enter_data.py                          # Interactive entry
    python enter_data.py --import csv data.csv    # Bulk import from CSV
    python enter_data.py --template               # Generate blank CSV template
"""

import sqlite3
import os
import sys
import csv
import argparse
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'endowments.db')
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed', 'entry_template.csv')


def list_institutions(conn):
    """Print all institutions for reference."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, short_name, tier FROM institutions ORDER BY tier, short_name")
    print("\nAvailable institutions:")
    print(f"{'ID':<15} {'Name':<20} {'Tier'}")
    print("-" * 50)
    for row in cursor.fetchall():
        print(f"{row[0]:<15} {row[1]:<20} {row[2]}")


def enter_annual(conn):
    """Interactive entry for one institution-year of data."""
    cursor = conn.cursor()
    list_institutions(conn)

    print("\n--- Enter Annual Endowment Data ---")
    inst = input("Institution ID (e.g., 'harvard'): ").strip()
    year = int(input("Fiscal year (e.g., 2023): ").strip())

    # Check if record exists
    cursor.execute(
        "SELECT id FROM endowment_annual WHERE institution_id = ? AND fiscal_year = ?",
        (inst, year)
    )
    existing = cursor.fetchone()
    if existing:
        overwrite = input(f"  Data exists for {inst} FY{year}. Overwrite? (y/n): ").strip().lower()
        if overwrite != 'y':
            print("  Skipped.")
            return

    print("\nLeave blank to skip a field. Enter values in MILLIONS for dollar amounts.\n")

    def get_float(prompt):
        val = input(prompt).strip()
        return float(val) if val else None

    def get_str(prompt):
        val = input(prompt).strip()
        return val if val else None

    value = get_float("  Endowment value ($ millions): ")
    ret = get_float("  Annual return (%): ")
    spending = get_float("  Spending/payout ($ millions): ")
    spending_rate = get_float("  Spending rate (%): ")
    spending_budget = get_float("  Spending as % of operating budget: ")
    gifts = get_float("  New gifts/contributions ($ millions): ")

    source_type = get_str("  Source type (990/financial_statement/investment_report): ") or 'financial_statement'
    source_url = get_str("  Source URL: ")
    source_title = get_str("  Source document title: ")
    confidence = get_str("  Confidence level (high/medium/low): ") or 'high'
    notes = get_str("  Notes: ")

    # Create source record
    cursor.execute("""
        INSERT INTO sources (institution_id, source_type, title, fiscal_year, url, date_accessed)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (inst, source_type, source_title or f"{source_type} FY{year}", year, source_url, datetime.now().strftime('%Y-%m-%d')))
    source_id = cursor.lastrowid

    # Insert or update annual data
    if existing:
        cursor.execute("""
            UPDATE endowment_annual SET
                endowment_value_millions = ?, endowment_value_source_id = ?, endowment_value_confidence = ?,
                annual_return_pct = ?, return_source_id = ?, return_confidence = ?,
                spending_millions = ?, spending_rate_pct = ?, spending_as_pct_of_budget = ?,
                spending_source_id = ?,
                new_gifts_millions = ?, gifts_source_id = ?,
                notes = ?, data_quality_score = ?
            WHERE institution_id = ? AND fiscal_year = ?
        """, (
            value, source_id, confidence,
            ret, source_id, confidence,
            spending, spending_rate, spending_budget,
            source_id,
            gifts, source_id,
            notes, 3 if confidence == 'high' else 2,
            inst, year
        ))
    else:
        cursor.execute("""
            INSERT INTO endowment_annual
                (institution_id, fiscal_year,
                 endowment_value_millions, endowment_value_source_id, endowment_value_confidence,
                 annual_return_pct, return_source_id, return_confidence,
                 spending_millions, spending_rate_pct, spending_as_pct_of_budget, spending_source_id,
                 new_gifts_millions, gifts_source_id,
                 notes, data_quality_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            inst, year,
            value, source_id, confidence,
            ret, source_id, confidence,
            spending, spending_rate, spending_budget, source_id,
            gifts, source_id,
            notes, 3 if confidence == 'high' else 2
        ))

    conn.commit()
    print(f"\n  ✓ Saved {inst} FY{year}")


def enter_allocation(conn):
    """Interactive entry for asset allocation data."""
    cursor = conn.cursor()
    list_institutions(conn)

    print("\n--- Enter Asset Allocation Data ---")
    inst = input("Institution ID: ").strip()
    year = int(input("Fiscal year: ").strip())

    # Show taxonomy for reference
    cursor.execute("SELECT id, category, subcategory FROM asset_class_taxonomy ORDER BY category, subcategory")
    print("\nAsset class taxonomy:")
    print(f"{'ID':<25} {'Category':<20} {'Subcategory'}")
    print("-" * 65)
    for row in cursor.fetchall():
        print(f"{row[0]:<25} {row[1]:<20} {row[2]}")

    print("\nEnter allocations. Type 'done' when finished.\n")

    while True:
        reported = input("  Reported category name (or 'done'): ").strip()
        if reported.lower() == 'done':
            break

        pct = float(input("  Percentage (%): ").strip())
        taxonomy_id = input("  Taxonomy ID from list above (or blank if unclear): ").strip() or None
        confidence = input("  Confidence (high/medium/low): ").strip() or 'high'
        inference = None
        if confidence != 'high':
            inference = input("  Inference method: ").strip()

        cursor.execute("""
            INSERT INTO asset_allocation
                (institution_id, fiscal_year, reported_category, reported_pct,
                 taxonomy_id, confidence, inference_method)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (inst, year, reported, pct, taxonomy_id, confidence, inference))

    conn.commit()

    # Check sum
    cursor.execute("""
        SELECT SUM(reported_pct) FROM asset_allocation
        WHERE institution_id = ? AND fiscal_year = ?
    """, (inst, year))
    total = cursor.fetchone()[0]
    if total and abs(total - 100) > 2:
        print(f"\n  ⚠ Allocation sums to {total:.1f}% (expected ~100%)")
    else:
        print(f"\n  ✓ Allocation saved ({total:.1f}% total)")


def generate_template():
    """Generate a CSV template for bulk data entry."""
    os.makedirs(os.path.dirname(TEMPLATE_PATH), exist_ok=True)

    headers = [
        'institution_id', 'fiscal_year',
        'endowment_value_millions', 'annual_return_pct',
        'spending_millions', 'spending_rate_pct', 'spending_as_pct_of_budget',
        'new_gifts_millions',
        'source_type', 'source_url', 'source_title',
        'confidence', 'notes'
    ]

    # Pre-fill with all institution-year combinations
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM institutions ORDER BY id")
    institutions = [row[0] for row in cursor.fetchall()]
    conn.close()

    with open(TEMPLATE_PATH, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for inst in institutions:
            for year in range(2000, 2025):
                writer.writerow([inst, year] + [''] * (len(headers) - 2))

    print(f"Template generated: {TEMPLATE_PATH}")
    print(f"  {len(institutions) * 25} rows (24 institutions × 25 years)")
    print(f"  Fill in the data, then import with: python enter_data.py --import csv {TEMPLATE_PATH}")


def import_csv(conn, filepath):
    """Bulk import from a filled-in CSV template."""
    cursor = conn.cursor()
    imported = 0
    skipped = 0

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            inst = row['institution_id'].strip()
            year = int(row['fiscal_year'])

            # Skip empty rows
            if not row.get('endowment_value_millions') and not row.get('annual_return_pct'):
                skipped += 1
                continue

            # Create source
            source_type = row.get('source_type', 'financial_statement').strip() or 'financial_statement'
            cursor.execute("""
                INSERT INTO sources (institution_id, source_type, title, fiscal_year, url, date_accessed)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                inst, source_type,
                row.get('source_title', f'{source_type} FY{year}'),
                year,
                row.get('source_url', ''),
                datetime.now().strftime('%Y-%m-%d')
            ))
            source_id = cursor.lastrowid

            confidence = row.get('confidence', 'high').strip() or 'high'

            def to_float(val):
                v = val.strip() if val else ''
                return float(v) if v else None

            cursor.execute("""
                INSERT INTO endowment_annual
                    (institution_id, fiscal_year,
                     endowment_value_millions, endowment_value_source_id, endowment_value_confidence,
                     annual_return_pct, return_source_id, return_confidence,
                     spending_millions, spending_rate_pct, spending_as_pct_of_budget, spending_source_id,
                     new_gifts_millions, gifts_source_id,
                     notes, data_quality_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(institution_id, fiscal_year) DO UPDATE SET
                    endowment_value_millions = excluded.endowment_value_millions,
                    annual_return_pct = excluded.annual_return_pct,
                    spending_millions = excluded.spending_millions,
                    spending_rate_pct = excluded.spending_rate_pct,
                    spending_as_pct_of_budget = excluded.spending_as_pct_of_budget,
                    new_gifts_millions = excluded.new_gifts_millions,
                    notes = excluded.notes
            """, (
                inst, year,
                to_float(row.get('endowment_value_millions', '')), source_id, confidence,
                to_float(row.get('annual_return_pct', '')), source_id, confidence,
                to_float(row.get('spending_millions', '')),
                to_float(row.get('spending_rate_pct', '')),
                to_float(row.get('spending_as_pct_of_budget', '')),
                source_id,
                to_float(row.get('new_gifts_millions', '')), source_id,
                row.get('notes', ''),
                3 if confidence == 'high' else 2
            ))
            imported += 1

    conn.commit()
    print(f"\nImported: {imported} rows")
    print(f"Skipped: {skipped} empty rows")


def main():
    parser = argparse.ArgumentParser(description='Manual data entry for endowment database')
    parser.add_argument('--template', action='store_true', help='Generate blank CSV template')
    parser.add_argument('--import', dest='import_file', nargs=2, metavar=('FORMAT', 'PATH'),
                       help='Import from file (format: csv)')
    parser.add_argument('--allocation', action='store_true', help='Enter asset allocation data')
    args = parser.parse_args()

    if args.template:
        generate_template()
        return

    if not os.path.exists(DB_PATH):
        print(f"Database not found. Run schema.py first.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        if args.import_file:
            fmt, path = args.import_file
            if fmt == 'csv':
                import_csv(conn, path)
            else:
                print(f"Unknown format: {fmt}")
        elif args.allocation:
            enter_allocation(conn)
        else:
            while True:
                enter_annual(conn)
                again = input("\nEnter another? (y/n): ").strip().lower()
                if again != 'y':
                    break
    finally:
        conn.close()


if __name__ == '__main__':
    main()
