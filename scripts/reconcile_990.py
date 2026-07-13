"""
990 Reconciliation Cross-Check
==============================
Compares IRS 990 total assets (from the raw ProPublica JSONs in
data/raw/990s/) against endowment values in `endowment_annual` and writes
the comparison into `reconciliation_log`.

Per CLAUDE.md: 990 total assets != endowment value (difference typically
5-15%+ because total assets include plant, receivables, and non-endowment
investments). This check catches gross errors: an endowment value LARGER
than 990 total assets is impossible and flags a bad data point; a ratio far
outside the historical norm warrants a look.

Usage:
    python scripts/reconcile_990.py
    python scripts/reconcile_990.py --institution yale
"""

import sqlite3
import os
import json
import glob
import argparse
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'endowments.db')
RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw', '990s')
FIELD = 'endowment_value_vs_990_total_assets'


def main():
    ap = argparse.ArgumentParser(description='Reconcile endowment values against 990 total assets')
    ap.add_argument('--institution', type=str, help='Specific institution ID')
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Idempotent: rebuild this check's rows each run
    cur.execute("DELETE FROM reconciliation_log WHERE field_name = ?", (FIELD,))

    rows = []
    pattern = os.path.join(RAW_DIR, args.institution or '*', '*_filings.json')
    for path in sorted(glob.glob(pattern)):
        inst = os.path.basename(os.path.dirname(path))
        with open(path) as f:
            payload = json.load(f)
        # One filing per FY: keep the largest total-assets record. ProPublica
        # returns related small filings (990-T etc.) alongside the main 990;
        # anything under $100M is junk for institutions of this size.
        by_fy = {}
        for filing in payload.get('filings_with_data', []):
            fy = filing.get('tax_prd_yr')
            assets = filing.get('totassetsend')
            if not fy or not assets or assets < 1e8:
                continue
            if fy not in by_fy or assets > by_fy[fy]:
                by_fy[fy] = assets
        for fy, assets in sorted(by_fy.items()):
            cur.execute("""
                SELECT endowment_value_millions, endowment_value_source_id
                FROM endowment_annual
                WHERE institution_id = ? AND fiscal_year = ?
                  AND endowment_value_millions IS NOT NULL
            """, (inst, fy))
            hit = cur.fetchone()
            if not hit:
                continue
            endow_m, endow_src = hit
            assets_m = assets / 1e6
            diff_pct = round((assets_m - endow_m) / assets_m * 100, 1)
            cur.execute("""
                SELECT id FROM sources
                WHERE institution_id = ? AND source_type = '990' AND fiscal_year = ?
                LIMIT 1
            """, (inst, fy))
            src990 = cur.fetchone()
            cur.execute("""
                INSERT INTO reconciliation_log
                    (institution_id, fiscal_year, field_name,
                     source_a_id, source_a_value, source_b_id, source_b_value,
                     difference_pct, resolution, resolved_value, date_resolved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                inst, fy, FIELD,
                endow_src, endow_m,
                src990[0] if src990 else None, round(assets_m, 1),
                diff_pct,
                'Endowment value retained; 990 total assets include plant, '
                'receivables and non-endowment investments so a positive gap is expected',
                endow_m,
                datetime.now().strftime('%Y-%m-%d'),
            ))
            rows.append((inst, fy, endow_m, assets_m, diff_pct))

    conn.commit()

    print(f"Reconciliation rows written: {len(rows)}\n")
    print(f"{'Institution':<14} {'FY':<6} {'Endowment $M':>13} {'990 assets $M':>14} {'gap %':>7}")
    print("-" * 60)
    flags = []
    for inst, fy, endow, assets, diff in rows:
        marker = ''
        if endow > assets:
            marker = '  << IMPOSSIBLE: endowment exceeds total assets'
            flags.append((inst, fy))
        elif diff > 60 or diff < 5:
            marker = '  <- outside typical range, review'
        print(f"{inst:<14} {fy:<6} {endow:>13,.0f} {assets:>14,.0f} {diff:>6.1f}%{marker}")

    if flags:
        print(f"\n{len(flags)} IMPOSSIBLE combinations found - fix these data points:")
        for inst, fy in flags:
            print(f"  {inst} FY{fy}")
    else:
        print("\nNo impossible combinations (endowment > total assets) found.")
    conn.close()


if __name__ == '__main__':
    main()
