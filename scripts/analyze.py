"""
Phase 2: Quantitative Analysis
==============================
Computes risk-adjusted performance metrics per institution from the return
series in `endowment_annual`, benchmarked against the series in `benchmarks`.

Metrics:
  - Annualized (geometric) return, arithmetic mean, volatility
  - Sharpe ratio (excess over 3M T-bill), Sortino ratio (downside dev vs T-bill)
  - Max drawdown of the cumulative return index + crisis-regime returns
    (dot-com FY01-02, GFC FY08-09, COVID FY20, rate shock FY22-23)
  - Excess return vs 60/40 and S&P 500 (matched years only)
  - Real (CPI-adjusted) annualized return
  - GFC recovery: fiscal years until endowment value regained its FY2008 level
  - Partial composite score: returns 30% + risk-adjusted 30% + drawdown/recovery
    15%, renormalized to 100 (allocation 15% and governance 10% components are
    not yet collectable - flagged in output)

Institutions with fewer than MIN_YEARS return observations are reported but
not ranked. Confidence caveats: most inputs are medium/low confidence pending
primary-source verification (see docs/phase1_status.md).

Usage:
    python scripts/analyze.py                # writes output/ + prints summary
    python scripts/analyze.py --min-years 12
"""

import sqlite3
import os
import csv
import math
import argparse
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'endowments.db')
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')

MIN_YEARS_DEFAULT = 8

REGIMES = {
    'dotcom_fy01_02': [2001, 2002],
    'gfc_fy08_09': [2008, 2009],
    'covid_fy20': [2020],
    'rate_shock_fy22_23': [2022, 2023],
}


def geo_annualized(returns):
    prod = 1.0
    for r in returns:
        prod *= (1 + r / 100.0)
    return (prod ** (1.0 / len(returns)) - 1) * 100


def stdev(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def cumulative(returns):
    prod = 1.0
    for r in returns:
        prod *= (1 + r / 100.0)
    return (prod - 1) * 100


def max_drawdown(year_returns):
    """Peak-to-trough decline of the cumulative index built from returns."""
    index, peak, mdd = 1.0, 1.0, 0.0
    for _, r in sorted(year_returns.items()):
        index *= (1 + r / 100.0)
        peak = max(peak, index)
        mdd = min(mdd, (index - peak) / peak)
    return mdd * 100


def load(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT e.institution_id, i.short_name, i.tier, i.fiscal_year_end,
               e.fiscal_year, e.annual_return_pct, e.endowment_value_millions,
               e.return_confidence
        FROM endowment_annual e JOIN institutions i ON i.id = e.institution_id
        ORDER BY e.institution_id, e.fiscal_year
    """)
    data = {}
    for inst, name, tier, fye, fy, ret, val, rconf in cur.fetchall():
        d = data.setdefault(inst, {'name': name, 'tier': tier, 'fye': fye,
                                   'returns': {}, 'values': {}, 'ret_conf': {}})
        if ret is not None:
            d['returns'][fy] = ret
            d['ret_conf'][fy] = rconf
        if val is not None:
            d['values'][fy] = val

    cur.execute("SELECT fiscal_year, benchmark_name, return_pct FROM benchmarks")
    bench = {}
    for fy, name, r in cur.fetchall():
        bench.setdefault(name, {})[fy] = r
    return data, bench


def gfc_recovery_years(values):
    """Fiscal years after 2008 until value regained the FY2008 level."""
    if 2008 not in values:
        return None
    peak = values[2008]
    for fy in sorted(values):
        if fy > 2008 and values[fy] >= peak:
            return fy - 2008
    return None  # never recovered in sample (or data gap)


def analyze_institution(d, bench, min_years):
    rets = d['returns']
    years = sorted(rets)
    m = {'n_years': len(years),
         'year_span': f"{years[0]}-{years[-1]}" if years else "-",
         'ranked': len(years) >= min_years}
    if years:
        solid = sum(1 for y in years if d['ret_conf'].get(y) in ('high', 'medium'))
        m['ret_conf_medium_plus_pct'] = round(solid / len(years) * 100)

    if years:
        rs = [rets[y] for y in years]
        m['geo_return'] = geo_annualized(rs)
        m['volatility'] = stdev(rs)

        rf = bench.get('tbill_3m', {})
        matched = [(rets[y], rf[y]) for y in years if y in rf]
        if len(matched) >= 2:
            excess = [r - f for r, f in matched]
            vol = stdev([r for r, _ in matched])
            m['sharpe'] = (sum(excess) / len(excess)) / vol if vol else None
            downside = [min(0.0, e) for e in excess]
            dd = math.sqrt(sum(x * x for x in downside) / len(downside))
            m['sortino'] = (sum(excess) / len(excess)) / dd if dd > 0 else None

        m['max_drawdown'] = max_drawdown(rets)

        cpi = bench.get('cpi', {})
        realr = [(1 + rets[y] / 100) / (1 + cpi[y] / 100) - 1 for y in years if y in cpi]
        if realr:
            prod = 1.0
            for r in realr:
                prod *= (1 + r)
            m['real_geo_return'] = (prod ** (1.0 / len(realr)) - 1) * 100

        for bname, key in [('60_40', 'excess_vs_6040'), ('sp500', 'excess_vs_sp500')]:
            b = bench.get(bname, {})
            diffs = [rets[y] - b[y] for y in years if y in b]
            if diffs:
                m[key] = sum(diffs) / len(diffs)

        for regime, req in REGIMES.items():
            if all(y in rets for y in req):
                m[regime] = cumulative([rets[y] for y in req])

    m['gfc_recovery_years'] = gfc_recovery_years(d['values'])
    return m


def rank_scores(results, min_years):
    """Partial composite: returns 30 + risk-adjusted 30 + drawdown/recovery 15,
    renormalized to 100. Rank-based (best rank = full points per component)."""
    ranked = {k: v for k, v in results.items() if v['metrics']['ranked']}

    def component(key, reverse):
        vals = {k: v['metrics'].get(key) for k, v in ranked.items()
                if v['metrics'].get(key) is not None}
        order = sorted(vals, key=lambda k: vals[k], reverse=reverse)  # best first
        n = len(order)
        return {k: (n - 1 - i) / (n - 1) if n > 1 else 1.0 for i, k in enumerate(order)}

    ret_s = component('geo_return', reverse=True)
    sharpe_s = component('sharpe', reverse=True)
    mdd_s = component('max_drawdown', reverse=True)   # least-negative drawdown best
    rec = {k: v['metrics'].get('gfc_recovery_years') for k, v in ranked.items()}
    rec_known = {k: y for k, y in rec.items() if y is not None}
    rec_order = sorted(rec_known, key=lambda k: rec_known[k])  # fastest recovery first
    nrec = len(rec_order)
    rec_s = {k: (nrec - 1 - i) / (nrec - 1) if nrec > 1 else 1.0
             for i, k in enumerate(rec_order)}

    for k, v in ranked.items():
        parts, weights = [], []
        for score_map, w in [(ret_s, 30), (sharpe_s, 30), (mdd_s, 7.5), (rec_s, 7.5)]:
            if k in score_map:
                parts.append(score_map[k] * w)
                weights.append(w)
        v['metrics']['composite_partial'] = (
            round(sum(parts) / sum(weights) * 100, 1) if weights else None)


def fmt(x, nd=1, suffix=''):
    if x is None:
        return '-'
    return f"{x:.{nd}f}{suffix}"


def main():
    ap = argparse.ArgumentParser(description='Phase 2 quantitative analysis')
    ap.add_argument('--min-years', type=int, default=MIN_YEARS_DEFAULT,
                    help='Minimum return observations to be ranked')
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    data, bench = load(conn)
    conn.close()

    if not bench.get('tbill_3m'):
        print("Benchmarks missing - run scripts/seed_benchmarks.py first.")
        return

    results = {}
    for inst, d in data.items():
        results[inst] = {'name': d['name'], 'tier': d['tier'], 'fye': d['fye'],
                         'metrics': analyze_institution(d, bench, args.min_years)}
    rank_scores(results, args.min_years)

    os.makedirs(OUT_DIR, exist_ok=True)

    cols = ['n_years', 'year_span', 'ret_conf_medium_plus_pct',
            'geo_return', 'real_geo_return', 'volatility',
            'sharpe', 'sortino', 'max_drawdown', 'gfc_recovery_years',
            'excess_vs_6040', 'excess_vs_sp500',
            'dotcom_fy01_02', 'gfc_fy08_09', 'covid_fy20', 'rate_shock_fy22_23',
            'composite_partial', 'ranked']
    csv_path = os.path.join(OUT_DIR, 'phase2_metrics.csv')
    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['institution_id', 'short_name', 'tier', 'fye'] + cols)
        for inst in sorted(results):
            r = results[inst]
            w.writerow([inst, r['name'], r['tier'], r['fye']] +
                       [r['metrics'].get(c) for c in cols])

    ranked = sorted((r for r in results.values()
                     if r['metrics'].get('composite_partial') is not None),
                    key=lambda r: -r['metrics']['composite_partial'])

    md_path = os.path.join(OUT_DIR, 'phase2_report.md')
    with open(md_path, 'w') as f:
        f.write(f"# Phase 2 Metrics Report\n\n*Generated {datetime.now():%Y-%m-%d}. "
                f"Ranked = at least {args.min_years} return observations.*\n\n")
        f.write("## Caveats\n\n"
                "- Inputs are medium/low confidence pending primary-source "
                "verification (docs/phase1_status.md). Rankings are provisional.\n"
                "- Composite is PARTIAL: returns 30% + risk-adjusted 30% + "
                "drawdown/recovery 15%, renormalized to 100. Allocation-evolution "
                "(15%) and governance (10%) components await Phase 1 allocation "
                "data and Phase 3 qualitative work.\n"
                "- Stanford, Northwestern, UT System, Texas A&M have Aug-31 FYE; "
                "their crisis-window returns lag June-FYE peers by two months.\n"
                "- Return series lengths differ; Sharpe/volatility across "
                "institutions with different spans are not strictly comparable.\n"
                "- Missing data is flagged, never estimated (docs/uncertainty.md). "
                "The full institution-by-year picture is in "
                "output/data_coverage_map.md. `Conf` = share of return "
                "observations at medium-or-better confidence.\n\n")
        f.write("## Provisional ranking (partial composite)\n\n")
        f.write("| # | Institution | Tier | Yrs | Conf | Ann. return | Real | Vol | Sharpe "
                "| MaxDD | GFC rec (yrs) | vs 60/40 | Composite |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(ranked, 1):
            m = r['metrics']
            f.write(f"| {i} | {r['name']} | {r['tier']} | {m['n_years']} "
                    f"| {m.get('ret_conf_medium_plus_pct', '-')}% "
                    f"| {fmt(m.get('geo_return'), 1, '%')} "
                    f"| {fmt(m.get('real_geo_return'), 1, '%')} "
                    f"| {fmt(m.get('volatility'), 1)} "
                    f"| {fmt(m.get('sharpe'), 2)} "
                    f"| {fmt(m.get('max_drawdown'), 1, '%')} "
                    f"| {m.get('gfc_recovery_years') if m.get('gfc_recovery_years') is not None else '-'} "
                    f"| {fmt(m.get('excess_vs_6040'), 1, '%')} "
                    f"| {m['composite_partial']} |\n")
        f.write("\n## Crisis regimes (cumulative return in window)\n\n")
        f.write("| Institution | Dot-com FY01-02 | GFC FY08-09 | COVID FY20 | Rate shock FY22-23 |\n")
        f.write("|---|---|---|---|---|\n")
        for inst in sorted(results, key=lambda k: results[k]['name']):
            m = results[inst]['metrics']
            if any(m.get(k) is not None for k in REGIMES):
                f.write(f"| {results[inst]['name']} "
                        f"| {fmt(m.get('dotcom_fy01_02'), 1, '%')} "
                        f"| {fmt(m.get('gfc_fy08_09'), 1, '%')} "
                        f"| {fmt(m.get('covid_fy20'), 1, '%')} "
                        f"| {fmt(m.get('rate_shock_fy22_23'), 1, '%')} |\n")
        unranked = [r['name'] for r in results.values()
                    if not r['metrics']['ranked']]
        f.write(f"\n## Not ranked (insufficient return data)\n\n"
                f"{', '.join(sorted(unranked))}\n\n"
                f"Per the missing-data policy these are excluded rather than "
                f"padded with estimates; they enter the ranking only when "
                f"citable return series are collected.\n")

    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}\n")
    print(f"{'#':<3} {'Institution':<14} {'Yrs':<4} {'AnnRet':<8} {'Sharpe':<7} "
          f"{'MaxDD':<8} {'Composite'}")
    print("-" * 60)
    for i, r in enumerate(ranked, 1):
        m = r['metrics']
        print(f"{i:<3} {r['name']:<14} {m['n_years']:<4} "
              f"{fmt(m.get('geo_return'), 1, '%'):<8} {fmt(m.get('sharpe'), 2):<7} "
              f"{fmt(m.get('max_drawdown'), 1, '%'):<8} {m['composite_partial']}")
    print(f"\nUnranked (< {args.min_years} return years): "
          f"{', '.join(sorted(r['name'] for r in results.values() if not r['metrics']['ranked']))}")


if __name__ == '__main__':
    main()
