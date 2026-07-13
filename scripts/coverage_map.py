"""
Data Coverage Map
=================
Renders the institution x fiscal-year grid of what data exists, making
missingness explicit (see docs/uncertainty.md — gaps are flagged, not filled).

Cell legend:
    B  value + return          V  value only
    r  return only             .  nothing (flagged missing)

Writes output/data_coverage_map.md and prints the grid.

Usage:
    python scripts/coverage_map.py
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'endowments.db')
OUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'output', 'data_coverage_map.md')
YEARS = list(range(2000, 2025))


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT i.id, i.short_name, i.tier,
               e.fiscal_year,
               e.endowment_value_millions IS NOT NULL,
               e.annual_return_pct IS NOT NULL,
               e.endowment_value_confidence
        FROM institutions i
        LEFT JOIN endowment_annual e ON e.institution_id = i.id
        ORDER BY i.tier, i.short_name, e.fiscal_year
    """)

    grid, conf, tiers = {}, {}, {}
    for iid, name, tier, fy, has_v, has_r, vconf in cur.fetchall():
        key = (tier, name)
        tiers.setdefault(key, iid)
        grid.setdefault(key, {})
        conf.setdefault(key, {'high': 0, 'medium': 0, 'low': 0})
        if fy is None:
            continue
        if has_v and has_r:
            cell = 'B'
        elif has_v:
            cell = 'V'
        elif has_r:
            cell = 'r'
        else:
            cell = '.'
        grid[key][fy] = cell
        if has_v and vconf in conf[key]:
            conf[key][vconf] += 1
    conn.close()

    lines = []
    lines.append(f"# Data Coverage Map\n")
    lines.append(f"*Generated {datetime.now():%Y-%m-%d}. "
                 f"`B` value+return · `V` value only · `r` return only · `.` missing (flagged, not filled — see docs/uncertainty.md)*\n")
    header = f"{'Institution':<14} " + ' '.join(f"{y % 100:02d}" for y in YEARS) + "   V-conf (h/m/l)"
    sep = "-" * len(header)

    lines.append("```")
    current_tier = None
    total_cells = filled = 0
    for (tier, name) in sorted(grid):
        if tier != current_tier:
            lines.append(f"\n[{tier.upper()}]")
            lines.append(header)
            lines.append(sep)
            current_tier = tier
        cells = []
        for y in YEARS:
            c = grid[(tier, name)].get(y, '.')
            cells.append(f" {c}")
            total_cells += 1
            if c != '.':
                filled += 1
        cf = conf[(tier, name)]
        lines.append(f"{name:<14}" + ''.join(cells) +
                     f"   {cf['high']}/{cf['medium']}/{cf['low']}")
    lines.append("```")

    lines.append(f"\n**Coverage: {filled}/{total_cells} institution-years "
                 f"({filled / total_cells * 100:.0f}%) — the remaining "
                 f"{total_cells - filled} cells are documented gaps, not oversights.**\n")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    print('\n'.join(lines))
    print(f"\nWrote {OUT_PATH}")


if __name__ == '__main__':
    main()
