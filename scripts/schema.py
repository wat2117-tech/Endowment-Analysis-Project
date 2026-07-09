"""
Endowment Performance Database Schema
======================================
Creates a normalized SQLite database for tracking university endowment
performance, asset allocation, leadership, and qualitative events.

Run this script to initialize the database:
    python schema.py

The schema is designed around these principles:
1. Every data point links to a source document (provenance)
2. Confidence levels are tracked for inferred/estimated values
3. Institution-specific reporting taxonomies map to a standardized taxonomy
4. Temporal consistency: all data normalized to fiscal year ending June 30
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'endowments.db')

SCHEMA = """
-- ============================================================
-- REFERENCE TABLES
-- ============================================================

-- Master institution list with metadata
CREATE TABLE IF NOT EXISTS institutions (
    id TEXT PRIMARY KEY,                    -- e.g., 'harvard', 'yale', 'ut_system'
    name TEXT NOT NULL,                     -- Full name
    short_name TEXT NOT NULL,               -- Display name
    tier TEXT NOT NULL,                     -- 'ivy', 'elite_private', 'public', 'lac'
    city TEXT,
    state TEXT,
    ein TEXT,                               -- IRS Employer Identification Number (for 990 lookups)
    founded INTEGER,
    student_count_approx INTEGER,           -- For per-student calculations
    is_system INTEGER DEFAULT 0,            -- 1 if multi-campus system (UT, Texas A&M, UC)
    investment_model TEXT,                  -- 'internal', 'ocio', 'hybrid'
    investment_entity_name TEXT,            -- e.g., 'Harvard Management Company', 'UVIMCO'
    fiscal_year_end TEXT DEFAULT '06-30',   -- MM-DD format
    notes TEXT
);

-- Standardized asset class taxonomy
-- Maps the inconsistent categories universities use to a common framework
CREATE TABLE IF NOT EXISTS asset_class_taxonomy (
    id TEXT PRIMARY KEY,                    -- e.g., 'public_equity_us', 'pe_buyout'
    category TEXT NOT NULL,                 -- Level 1: 'public_equity', 'fixed_income', 'alternatives', 'real_assets', 'cash'
    subcategory TEXT,                       -- Level 2: 'us_equity', 'intl_equity', 'buyout', 'venture', 'hedge_long_short'
    description TEXT,
    is_liquid INTEGER DEFAULT 1             -- 0 = illiquid (PE, VC, real estate), 1 = liquid
);

-- Source document registry — every data point traces back here
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    source_type TEXT NOT NULL,              -- '990', 'financial_statement', 'investment_report', '13f', 'nacubo', 'news', 'academic_paper', 'sec_filing'
    title TEXT,                             -- Document title
    fiscal_year INTEGER,                    -- Fiscal year the data pertains to
    url TEXT,                               -- Where to find it
    file_path TEXT,                         -- Local path to downloaded document
    date_accessed DATE,                     -- When we pulled it
    date_published DATE,
    notes TEXT
);

-- ============================================================
-- CORE DATA TABLES
-- ============================================================

-- Annual endowment snapshot — one row per institution per fiscal year
CREATE TABLE IF NOT EXISTS endowment_annual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    fiscal_year INTEGER NOT NULL,           -- e.g., 2023 means FY ending June 2023

    -- Size & Growth
    endowment_value_millions REAL,          -- Total market value (end of fiscal year)
    endowment_value_source_id INTEGER REFERENCES sources(id),
    endowment_value_confidence TEXT DEFAULT 'high',  -- 'high', 'medium', 'low'

    -- Performance
    annual_return_pct REAL,                 -- Total return (net of fees unless noted)
    return_net_of_fees INTEGER DEFAULT 1,   -- 1 = net, 0 = gross, NULL = unknown
    return_source_id INTEGER REFERENCES sources(id),
    return_confidence TEXT DEFAULT 'high',

    -- Spending
    spending_millions REAL,                 -- Total distributed to university operations
    spending_rate_pct REAL,                 -- Payout as % of endowment value
    spending_as_pct_of_budget REAL,         -- Endowment spending / total operating budget
    spending_source_id INTEGER REFERENCES sources(id),

    -- Inflows
    new_gifts_millions REAL,               -- New contributions received
    gifts_source_id INTEGER REFERENCES sources(id),

    -- Derived (calculated after data entry)
    real_return_pct REAL,                   -- Nominal return minus CPI inflation
    endowment_per_student REAL,             -- Value / student count
    growth_rate_yoy_pct REAL,               -- Year-over-year change in total value

    -- Metadata
    notes TEXT,
    data_quality_score INTEGER,             -- 1-5 scale, 5 = all primary sources reconciled

    UNIQUE(institution_id, fiscal_year)
);

-- Asset allocation breakdown — multiple rows per institution per year
CREATE TABLE IF NOT EXISTS asset_allocation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    fiscal_year INTEGER NOT NULL,

    -- What the institution reported
    reported_category TEXT NOT NULL,         -- Exact category name from their report
    reported_pct REAL,                      -- % they reported

    -- Our standardized mapping
    taxonomy_id TEXT REFERENCES asset_class_taxonomy(id),

    -- Data quality
    source_id INTEGER REFERENCES sources(id),
    confidence TEXT DEFAULT 'high',         -- 'high' = directly reported, 'medium' = inferred from peer/pattern, 'low' = rough estimate
    inference_method TEXT,                  -- If not 'high': explain how we estimated

    notes TEXT
);

-- ============================================================
-- LEADERSHIP & GOVERNANCE
-- ============================================================

-- CIO and senior investment leadership
CREATE TABLE IF NOT EXISTS leadership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    name TEXT NOT NULL,
    title TEXT,                             -- 'CIO', 'CEO of HMC', 'VP Investments'
    start_year INTEGER,
    end_year INTEGER,                       -- NULL if current
    background TEXT,                        -- Prior roles, education
    prior_firm TEXT,                        -- Where they came from
    prior_firm_type TEXT,                   -- 'pe', 'hf', 'endowment', 'consulting', 'banking', 'asset_mgmt'
    compensation_total REAL,               -- From 990, if available
    compensation_year INTEGER,
    compensation_source_id INTEGER REFERENCES sources(id),
    notes TEXT
);

-- Investment committee / board members (when available)
CREATE TABLE IF NOT EXISTS governance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    fiscal_year INTEGER NOT NULL,
    committee_name TEXT DEFAULT 'Investment Committee',
    member_count INTEGER,
    notable_members TEXT,                   -- JSON array of names/affiliations if available
    source_id INTEGER REFERENCES sources(id),
    notes TEXT
);

-- ============================================================
-- RISK & LIQUIDITY
-- ============================================================

-- Drawdown and crisis behavior
CREATE TABLE IF NOT EXISTS crisis_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    event_name TEXT NOT NULL,               -- 'dot_com_crash', 'gfc_2008', 'covid_2020', 'rate_shock_2022'
    peak_value_millions REAL,
    trough_value_millions REAL,
    drawdown_pct REAL,                      -- Peak-to-trough decline
    recovery_quarters INTEGER,              -- Quarters to recover to peak
    forced_actions TEXT,                    -- e.g., 'sold PE secondaries', 'drew credit line', 'cut spending'
    source_id INTEGER REFERENCES sources(id),
    notes TEXT
);

-- ============================================================
-- QUALITATIVE EVENTS & CONTEXT
-- ============================================================

-- Notable events, strategy shifts, controversies
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    event_date DATE,
    fiscal_year INTEGER,
    event_type TEXT NOT NULL,               -- 'strategy_shift', 'cio_change', 'divestment', 'controversy', 'policy_change', 'major_gift', 'structural_change'
    title TEXT NOT NULL,
    description TEXT,
    impact_on_performance TEXT,             -- Our assessment of how this affected returns
    source_id INTEGER REFERENCES sources(id)
);

-- ============================================================
-- SEC 13F HOLDINGS (Public Equities Only)
-- ============================================================

CREATE TABLE IF NOT EXISTS holdings_13f (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    quarter_end DATE NOT NULL,              -- e.g., 2023-06-30
    security_name TEXT,
    cusip TEXT,
    ticker TEXT,
    value_thousands REAL,                   -- Reported in thousands on 13F
    shares INTEGER,
    source_id INTEGER REFERENCES sources(id)
);

-- ============================================================
-- BENCHMARKS & COMPARISONS
-- ============================================================

-- Market benchmarks for the same periods
CREATE TABLE IF NOT EXISTS benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fiscal_year INTEGER NOT NULL,
    benchmark_name TEXT NOT NULL,           -- 'sp500', '60_40', 'nacubo_large', 'nacubo_all', 'cpi', 'yale_model_proxy'
    return_pct REAL NOT NULL,
    source_id INTEGER REFERENCES sources(id),

    UNIQUE(fiscal_year, benchmark_name)
);

-- ============================================================
-- DATA RECONCILIATION LOG
-- ============================================================

-- Track discrepancies between sources
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id TEXT NOT NULL REFERENCES institutions(id),
    fiscal_year INTEGER NOT NULL,
    field_name TEXT NOT NULL,               -- Which field has the discrepancy
    source_a_id INTEGER REFERENCES sources(id),
    source_a_value REAL,
    source_b_id INTEGER REFERENCES sources(id),
    source_b_value REAL,
    difference_pct REAL,                   -- % difference between sources
    resolution TEXT,                       -- Which value we used and why
    resolved_value REAL,
    date_resolved DATE
);

-- ============================================================
-- VIEWS (Convenience queries)
-- ============================================================

-- Quick performance overview
CREATE VIEW IF NOT EXISTS v_performance_summary AS
SELECT
    i.short_name,
    i.tier,
    e.fiscal_year,
    e.endowment_value_millions,
    e.annual_return_pct,
    e.spending_rate_pct,
    e.endowment_per_student,
    e.data_quality_score
FROM endowment_annual e
JOIN institutions i ON e.institution_id = i.id
ORDER BY i.tier, i.short_name, e.fiscal_year;

-- Asset allocation comparison (standardized)
CREATE VIEW IF NOT EXISTS v_allocation_comparison AS
SELECT
    i.short_name,
    i.tier,
    a.fiscal_year,
    t.category,
    t.subcategory,
    a.reported_pct,
    a.confidence,
    a.inference_method
FROM asset_allocation a
JOIN institutions i ON a.institution_id = i.id
LEFT JOIN asset_class_taxonomy t ON a.taxonomy_id = t.id
ORDER BY i.short_name, a.fiscal_year, t.category;

-- CIO tenure and performance correlation
CREATE VIEW IF NOT EXISTS v_cio_performance AS
SELECT
    i.short_name,
    l.name AS cio_name,
    l.start_year,
    l.end_year,
    l.prior_firm_type,
    l.compensation_total,
    AVG(e.annual_return_pct) AS avg_annual_return,
    COUNT(e.fiscal_year) AS years_measured
FROM leadership l
JOIN institutions i ON l.institution_id = i.id
LEFT JOIN endowment_annual e ON e.institution_id = l.institution_id
    AND e.fiscal_year BETWEEN l.start_year AND COALESCE(l.end_year, 2025)
GROUP BY i.short_name, l.name, l.start_year
ORDER BY avg_annual_return DESC;

-- Crisis comparison across institutions
CREATE VIEW IF NOT EXISTS v_crisis_comparison AS
SELECT
    i.short_name,
    i.tier,
    c.event_name,
    c.drawdown_pct,
    c.recovery_quarters,
    c.forced_actions
FROM crisis_events c
JOIN institutions i ON c.institution_id = i.id
ORDER BY c.event_name, c.drawdown_pct;
""";

# Seed data for standardized asset class taxonomy
TAXONOMY_SEED = [
    # Public Markets
    ('pub_eq_us', 'public_equity', 'us_equity', 'US public equities (large, mid, small cap)', 1),
    ('pub_eq_intl_dev', 'public_equity', 'intl_developed', 'International developed market equities', 1),
    ('pub_eq_em', 'public_equity', 'emerging_markets', 'Emerging market equities', 1),
    ('fi_gov', 'fixed_income', 'government', 'US Treasuries, sovereign bonds', 1),
    ('fi_corp', 'fixed_income', 'corporate', 'Investment grade and high yield corporate bonds', 1),
    ('fi_tips', 'fixed_income', 'inflation_linked', 'TIPS, inflation-protected securities', 1),
    ('fi_intl', 'fixed_income', 'international', 'International fixed income', 1),

    # Private Markets
    ('pe_buyout', 'private_equity', 'buyout', 'Leveraged buyouts, growth equity', 0),
    ('pe_vc', 'private_equity', 'venture_capital', 'Early and late stage venture capital', 0),
    ('pe_distressed', 'private_equity', 'distressed', 'Distressed debt, special situations', 0),
    ('pe_secondary', 'private_equity', 'secondaries', 'Secondary market PE fund purchases', 0),
    ('pe_direct', 'private_equity', 'direct_coinvest', 'Direct and co-investments alongside GPs', 0),

    # Hedge Funds / Absolute Return
    ('hf_long_short', 'hedge_funds', 'long_short_equity', 'Long/short equity hedge funds', 1),
    ('hf_macro', 'hedge_funds', 'global_macro', 'Global macro, managed futures', 1),
    ('hf_event', 'hedge_funds', 'event_driven', 'Event-driven, merger arb, activist', 1),
    ('hf_multi', 'hedge_funds', 'multi_strategy', 'Multi-strategy hedge funds', 1),
    ('hf_quant', 'hedge_funds', 'quantitative', 'Systematic, quantitative strategies', 1),

    # Real Assets
    ('ra_real_estate', 'real_assets', 'real_estate', 'Real estate equity and debt', 0),
    ('ra_nat_resources', 'real_assets', 'natural_resources', 'Oil, gas, timber, mining, farmland', 0),
    ('ra_infra', 'real_assets', 'infrastructure', 'Infrastructure investments', 0),
    ('ra_commodities', 'real_assets', 'commodities', 'Commodity futures and physical', 1),

    # Cash & Other
    ('cash', 'cash', 'cash_equivalents', 'Cash, money market, short-term instruments', 1),
    ('other', 'other', 'other', 'Uncategorized or mixed', 1),

    # Catch-all buckets (for when institutions report vaguely)
    ('alt_undifferentiated', 'alternatives_undifferentiated', 'undifferentiated', 'Reported as "alternatives" without breakdown — maps to PE+HF+other', 0),
    ('abs_return', 'absolute_return', 'undifferentiated', 'Reported as "absolute return" — typically hedge fund strategies', 1),
]

# Seed data for institutions
INSTITUTION_SEED = [
    # Ivy League
    ('harvard', 'Harvard University', 'Harvard', 'ivy', 'Cambridge', 'MA', '04-2103580', 1636, 22000, 0, 'internal', 'Harvard Management Company', '06-30'),
    ('yale', 'Yale University', 'Yale', 'ivy', 'New Haven', 'CT', '06-0646973', 1701, 14800, 0, 'internal', 'Yale Investments Office', '06-30'),
    ('princeton', 'Princeton University', 'Princeton', 'ivy', 'Princeton', 'NJ', '21-0634501', 1746, 8800, 0, 'internal', 'Princeton University Investment Company', '06-30'),
    ('penn', 'University of Pennsylvania', 'Penn', 'ivy', 'Philadelphia', 'PA', '23-1352685', 1740, 22000, 0, 'internal', 'Office of Investments', '06-30'),
    ('columbia', 'Columbia University', 'Columbia', 'ivy', 'New York', 'NY', '13-5598093', 1754, 33000, 0, 'internal', 'Columbia Investment Management Company', '06-30'),
    ('cornell', 'Cornell University', 'Cornell', 'ivy', 'Ithaca', 'NY', '15-0532082', 1865, 25600, 0, 'internal', 'Cornell University Investment Office', '06-30'),
    ('dartmouth', 'Dartmouth College', 'Dartmouth', 'ivy', 'Hanover', 'NH', '02-0222111', 1769, 6800, 0, 'internal', 'Dartmouth Investment Office', '06-30'),
    ('brown', 'Brown University', 'Brown', 'ivy', 'Providence', 'RI', '05-0258809', 1764, 10600, 0, 'internal', 'Brown University Investment Office', '06-30'),

    # Elite Privates
    ('stanford', 'Stanford University', 'Stanford', 'elite_private', 'Stanford', 'CA', '94-1156365', 1885, 17600, 0, 'internal', 'Stanford Management Company', '08-31'),
    ('mit', 'Massachusetts Institute of Technology', 'MIT', 'elite_private', 'Cambridge', 'MA', '04-2103594', 1861, 11800, 0, 'internal', 'MIT Investment Management Company', '06-30'),
    ('duke', 'Duke University', 'Duke', 'elite_private', 'Durham', 'NC', '56-0532129', 1838, 17000, 0, 'internal', 'Duke University Management Company', '06-30'),
    ('uchicago', 'University of Chicago', 'UChicago', 'elite_private', 'Chicago', 'IL', '36-2177139', 1890, 17000, 0, 'hybrid', None, '06-30'),
    ('northwestern', 'Northwestern University', 'Northwestern', 'elite_private', 'Evanston', 'IL', '36-2167817', 1851, 22000, 0, 'internal', None, '08-31'),
    ('rice', 'Rice University', 'Rice', 'elite_private', 'Houston', 'TX', '74-1109620', 1912, 4400, 0, 'internal', 'Rice Management Company', '06-30'),

    # Public Universities
    ('ut_system', 'University of Texas System', 'UT System', 'public', 'Austin', 'TX', None, 1876, 240000, 1, 'internal', 'University of Texas Investment Management Company', '08-31'),
    ('tamu_system', 'Texas A&M University System', 'Texas A&M', 'public', 'College Station', 'TX', None, 1876, 150000, 1, 'internal', None, '08-31'),
    ('umich', 'University of Michigan', 'Michigan', 'public', 'Ann Arbor', 'MI', '38-6006309', 1817, 47000, 0, 'internal', None, '06-30'),
    ('uva', 'University of Virginia', 'UVA', 'public', 'Charlottesville', 'VA', '54-6001796', 1819, 26000, 0, 'internal', 'UVA Investment Management Company', '06-30'),
    ('berkeley', 'University of California, Berkeley', 'Berkeley', 'public', 'Berkeley', 'CA', None, 1868, 45000, 0, 'hybrid', None, '06-30'),

    # Liberal Arts Colleges
    ('williams', 'Williams College', 'Williams', 'lac', 'Williamstown', 'MA', '04-1767068', 1793, 2100, 0, 'hybrid', None, '06-30'),
    ('amherst', 'Amherst College', 'Amherst', 'lac', 'Amherst', 'MA', '04-1767060', 1821, 1900, 0, 'hybrid', None, '06-30'),
    ('pomona', 'Pomona College', 'Pomona', 'lac', 'Claremont', 'CA', '95-1644054', 1887, 1800, 0, 'ocio', None, '06-30'),
    ('grinnell', 'Grinnell College', 'Grinnell', 'lac', 'Grinnell', 'IA', '42-0680459', 1846, 1700, 0, 'hybrid', None, '06-30'),
    ('swarthmore', 'Swarthmore College', 'Swarthmore', 'lac', 'Swarthmore', 'PA', '23-1352040', 1864, 1600, 0, 'hybrid', None, '06-30'),
]


def create_database():
    """Initialize the database with schema and seed data."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # Create all tables and views
    cursor.executescript(SCHEMA)

    # Seed taxonomy
    cursor.executemany(
        """INSERT OR IGNORE INTO asset_class_taxonomy (id, category, subcategory, description, is_liquid)
           VALUES (?, ?, ?, ?, ?)""",
        TAXONOMY_SEED
    )

    # Seed institutions
    cursor.executemany(
        """INSERT OR IGNORE INTO institutions
           (id, name, short_name, tier, city, state, ein, founded, student_count_approx,
            is_system, investment_model, investment_entity_name, fiscal_year_end)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        INSTITUTION_SEED
    )

    conn.commit()

    # Print summary
    cursor.execute("SELECT tier, COUNT(*) FROM institutions GROUP BY tier ORDER BY tier")
    print("Database initialized at:", DB_PATH)
    print("\nInstitutions by tier:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]}")

    cursor.execute("SELECT COUNT(*) FROM asset_class_taxonomy")
    print(f"\nAsset class taxonomy: {cursor.fetchone()[0]} categories")

    print("\nTables created:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for row in cursor.fetchall():
        print(f"  {row[0]}")

    print("\nViews created:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
    for row in cursor.fetchall():
        print(f"  {row[0]}")

    conn.close()


if __name__ == '__main__':
    create_database()
