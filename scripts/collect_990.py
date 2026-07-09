"""
ProPublica 990 Data Collector
==============================
Pulls IRS Form 990 filing data for all institutions via the ProPublica
Nonprofit Explorer API.

API Docs: https://projects.propublica.org/nonprofits/api

Usage:
    python collect_990.py                 # Pull all institutions
    python collect_990.py --institution harvard  # Pull one
    python collect_990.py --year 2023     # Pull specific year
    python collect_990.py --download-pdfs # Also download raw 990 PDFs

What this extracts from 990s:
- Total assets / endowment proxy values
- Investment income (interest, dividends, capital gains)
- Total revenue and expenses
- Top compensated employees (CIO salary data)
- Tax period / fiscal year info

Limitations:
- 990 "total assets" ≠ endowment value (includes non-endowment assets)
- Asset breakdowns vary by form version and filing
- Some institutions file as part of a system (UT, Texas A&M)
- Public universities may not file 990s (state entities)
"""

import json
import os
import sys
import time
import sqlite3
import argparse
from datetime import datetime

# Optional: install with pip install requests --break-system-packages
try:
    import requests
except ImportError:
    print("Install requests: pip install requests --break-system-packages")
    sys.exit(1)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'endowments.db')
RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw', '990s')
API_BASE = "https://projects.propublica.org/nonprofits/api/v2"

# Rate limiting: ProPublica asks for reasonable use
REQUEST_DELAY = 1.0  # seconds between API calls


def get_institutions(conn, institution_id=None):
    """Fetch institutions that have EINs (can look up 990s)."""
    cursor = conn.cursor()
    if institution_id:
        cursor.execute(
            "SELECT id, name, short_name, ein, tier FROM institutions WHERE id = ? AND ein IS NOT NULL",
            (institution_id,)
        )
    else:
        cursor.execute(
            "SELECT id, name, short_name, ein, tier FROM institutions WHERE ein IS NOT NULL ORDER BY tier, id"
        )
    return cursor.fetchall()


def fetch_organization(ein):
    """
    Fetch organization overview from ProPublica API.
    Returns filing list and org metadata.
    """
    # Strip hyphens from EIN for API
    ein_clean = ein.replace('-', '')
    url = f"{API_BASE}/organizations/{ein_clean}.json"

    headers = {'User-Agent': 'EndowmentResearch/1.0 (academic research project)'}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        print(f"  HTTP Error for EIN {ein}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  Request failed for EIN {ein}: {e}")
        return None


def fetch_filing_detail(ein, tax_period):
    """
    Fetch detailed 990 filing data for a specific tax period.
    tax_period format: YYYYMM (e.g., 202306 for June 2023)
    """
    ein_clean = ein.replace('-', '')
    # ProPublica sometimes uses the filing object URL directly
    # We'll extract what we can from the org-level response
    pass


def extract_filing_data(filing, institution_id):
    """
    Extract relevant fields from a ProPublica filing record.
    Returns a dict ready for database insertion.
    """
    data = {
        'institution_id': institution_id,
        'tax_period': filing.get('tax_prd'),           # YYYYMM
        'tax_year': filing.get('tax_prd_yr'),          # YYYY
        'total_revenue': filing.get('totrevenue'),
        'total_expenses': filing.get('totfuncexpns'),
        'total_assets_eoy': filing.get('totassetsend'),
        'total_assets_boy': filing.get('totassetsbeg'),
        'investment_income': filing.get('invstmntinc'),
        'net_income': filing.get('totrevenue', 0) and filing.get('totfuncexpns', 0)
            and (filing.get('totrevenue', 0) - filing.get('totfuncexpns', 0)),
        'pdf_url': filing.get('pdf_url'),
        'form_type': filing.get('formtype'),            # 990, 990-PF, etc.
        'updated': filing.get('updated'),
    }

    # Derive fiscal year from tax period
    # Tax period 202306 = fiscal year ending June 2023 = FY2023
    if data['tax_period']:
        tp = str(data['tax_period'])
        if len(tp) >= 6:
            month = int(tp[4:6])
            year = int(tp[:4])
            # If fiscal year ends June or later, FY = that year
            # If fiscal year ends before June, FY = that year
            data['fiscal_year'] = year
        else:
            data['fiscal_year'] = data.get('tax_year')

    return data


def save_raw_json(data, institution_id, ein):
    """Save raw API response for provenance."""
    inst_dir = os.path.join(RAW_DIR, institution_id)
    os.makedirs(inst_dir, exist_ok=True)

    filepath = os.path.join(inst_dir, f"{institution_id}_{ein.replace('-','')}_filings.json")
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    return filepath


def download_pdf(url, institution_id, fiscal_year):
    """Download the actual 990 PDF for source provenance."""
    if not url:
        return None

    pdf_dir = os.path.join(RAW_DIR, institution_id, 'pdfs')
    os.makedirs(pdf_dir, exist_ok=True)

    filename = f"{institution_id}_990_{fiscal_year}.pdf"
    filepath = os.path.join(pdf_dir, filename)

    if os.path.exists(filepath):
        return filepath

    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(resp.content)
        return filepath
    except Exception as e:
        print(f"    Failed to download PDF: {e}")
        return None


def store_filing(conn, filing_data, raw_filepath):
    """
    Store extracted 990 data into the database.
    Creates source record + updates endowment_annual where possible.
    """
    cursor = conn.cursor()
    institution_id = filing_data['institution_id']
    fiscal_year = filing_data.get('fiscal_year')

    if not fiscal_year:
        return

    # 1. Create source record
    cursor.execute("""
        INSERT OR IGNORE INTO sources
            (institution_id, source_type, title, fiscal_year, url, file_path, date_accessed)
        VALUES (?, '990', ?, ?, ?, ?, ?)
    """, (
        institution_id,
        f"IRS Form 990 - FY{fiscal_year}",
        fiscal_year,
        filing_data.get('pdf_url'),
        raw_filepath,
        datetime.now().strftime('%Y-%m-%d')
    ))

    source_id = cursor.lastrowid

    # 2. Insert/update endowment_annual with what 990 provides
    # Note: 990 total_assets ≠ endowment value, but it's a data point
    # We store it and reconcile later with audited financials
    cursor.execute("""
        INSERT INTO endowment_annual
            (institution_id, fiscal_year, notes, data_quality_score)
        VALUES (?, ?, '990 data loaded - needs reconciliation with audited financials', 1)
        ON CONFLICT(institution_id, fiscal_year) DO NOTHING
    """, (institution_id, fiscal_year))

    conn.commit()
    return source_id


def collect_all(conn, institution_id=None, target_year=None, download_pdfs=False):
    """Main collection loop."""
    institutions = get_institutions(conn, institution_id)

    if not institutions:
        print("No institutions with EINs found. Run schema.py first.")
        return

    print(f"\nCollecting 990 data for {len(institutions)} institutions...")
    print(f"{'='*60}")

    results_summary = []

    for inst_id, name, short_name, ein, tier in institutions:
        print(f"\n[{tier.upper()}] {short_name} (EIN: {ein})")

        # Fetch from ProPublica
        org_data = fetch_organization(ein)
        time.sleep(REQUEST_DELAY)

        if not org_data:
            print(f"  ✗ No data returned")
            results_summary.append((short_name, tier, 0, 'API error'))
            continue

        # Check for organization info
        org_info = org_data.get('organization', {})
        filings = org_data.get('filings_with_data', [])
        filings_no_data = org_data.get('filings_without_data', [])

        print(f"  Found {len(filings)} filings with data, {len(filings_no_data)} without")

        # Save raw JSON
        raw_path = save_raw_json(org_data, inst_id, ein)
        print(f"  Raw JSON saved: {raw_path}")

        # Process each filing
        count = 0
        for filing in filings:
            filing_data = extract_filing_data(filing, inst_id)
            fy = filing_data.get('fiscal_year')

            # Skip if targeting specific year
            if target_year and fy != target_year:
                continue

            # Skip if outside our analysis window
            if fy and (fy < 2000 or fy > 2025):
                continue

            store_filing(conn, filing_data, raw_path)
            count += 1

            if download_pdfs and filing_data.get('pdf_url'):
                pdf_path = download_pdf(filing_data['pdf_url'], inst_id, fy)
                if pdf_path:
                    print(f"    FY{fy}: PDF downloaded")

            print(f"    FY{fy}: total_assets=${filing_data.get('total_assets_eoy', 'N/A'):,}" if filing_data.get('total_assets_eoy') else f"    FY{fy}: loaded (no asset data in API response)")

        results_summary.append((short_name, tier, count, 'OK'))

    # Print summary
    print(f"\n{'='*60}")
    print("COLLECTION SUMMARY")
    print(f"{'='*60}")
    print(f"{'Institution':<20} {'Tier':<15} {'Filings':<10} {'Status'}")
    print(f"{'-'*60}")
    for name, tier, count, status in results_summary:
        print(f"{name:<20} {tier:<15} {count:<10} {status}")

    # Flag institutions without EINs (public universities)
    cursor = conn.cursor()
    cursor.execute("SELECT short_name, tier FROM institutions WHERE ein IS NULL ORDER BY tier")
    no_ein = cursor.fetchall()
    if no_ein:
        print(f"\n⚠ Institutions without EINs (need manual data collection):")
        for name, tier in no_ein:
            print(f"  [{tier}] {name} — collect from audited financials / state records")


def main():
    parser = argparse.ArgumentParser(description='Collect 990 data from ProPublica')
    parser.add_argument('--institution', type=str, help='Specific institution ID')
    parser.add_argument('--year', type=int, help='Specific fiscal year')
    parser.add_argument('--download-pdfs', action='store_true', help='Download 990 PDFs')
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        print("Run schema.py first to initialize the database.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        collect_all(conn, args.institution, args.year, args.download_pdfs)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
