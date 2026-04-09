"""
Water Intelligence Engine v2
Pure stdlib Python (sqlite3) mirroring a SQLModel table architecture.
Maps directly to the Water_Model_v2 unified architecture (5 sections).

Changes from original:
- create_db() no longer DROPs tables; uses CREATE TABLE IF NOT EXISTS only.
- New migrate_db() applies schema_version-tracked migrations safely.
- init_db() replaces reset_database(): migrate then seed only if empty.
- seed_data() uses INSERT OR IGNORE for tank_environment (idempotent).
- WAL journal mode enabled on every new connection via _configure_conn().
- Index on daily_usage_by_day(activity_name, day_num) for fast per-day reads.
- compute_and_store() unchanged in logic; callers control when it runs.
- __main__ still wipes the DB file for a clean CLI run (intended behaviour).
"""

import sqlite3
import math
import os
import sys
import random

# Ensure UTF-8 output on Windows so emoji/box-drawing characters print correctly
if os.name == "nt" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = os.environ.get(
    "WATER_INTELLIGENCE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "water_intelligence.db"),
)

# ── Current schema version (bump when adding migrations below) ────────────────
_SCHEMA_VERSION = 1


def _configure_conn(conn: sqlite3.Connection) -> None:
    """Apply connection-level PRAGMAs. Call immediately after sqlite3.connect()."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row


def get_connection(path: str = DB_PATH) -> sqlite3.Connection:
    """Open and configure a new SQLite connection."""
    # FastAPI runs sync endpoints in a threadpool; allow this connection
    # to be accessed across worker threads (api.py serializes access via a lock).
    conn = sqlite3.connect(path, check_same_thread=False)
    _configure_conn(conn)
    return conn


# ── Schema creation (safe, idempotent) ───────────────────────────────────────

def create_db(conn: sqlite3.Connection) -> None:
    """
    Create all tables if they do not already exist.
    Never drops anything — safe to call on a live database.
    """
    cur = conn.cursor()
    cur.executescript("""
    -- Migration tracking
    CREATE TABLE IF NOT EXISTS schema_version (
        version  INTEGER PRIMARY KEY,
        applied  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- SECTION 1: People Inputs
    CREATE TABLE IF NOT EXISTS user_type (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        name     TEXT NOT NULL,
        count    INTEGER NOT NULL,
        is_child INTEGER NOT NULL DEFAULT 0,
        UNIQUE(name, is_child)
    );

    -- SECTION 2: Tank & Environment
    CREATE TABLE IF NOT EXISTS tank_environment (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        fresh_capacity_gal   REAL NOT NULL DEFAULT 100,
        grey_capacity_gal    REAL NOT NULL DEFAULT 80,
        black_capacity_gal   REAL NOT NULL DEFAULT 40,
        current_fresh_gal    REAL NOT NULL DEFAULT 100,
        current_grey_gal     REAL NOT NULL DEFAULT 0,
        current_black_gal    REAL NOT NULL DEFAULT 0,
        climate_multiplier   REAL NOT NULL DEFAULT 1.0,
        target_autonomy_days REAL NOT NULL DEFAULT 5,
        drift                REAL NOT NULL DEFAULT 0.0,
        drift_seed           INTEGER,
        alert_threshold      REAL NOT NULL DEFAULT 0.10,
        greywater_recycle    INTEGER NOT NULL DEFAULT 0
    );

    -- SECTION 3: Behavior Multipliers
    CREATE TABLE IF NOT EXISTS behavior_multiplier (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_type    TEXT NOT NULL UNIQUE,
        shower_mult  REAL NOT NULL,
        sink_mult    REAL NOT NULL,
        toilet_mult  REAL NOT NULL
    );

    -- SECTION 4: Activity Engine — base parameters
    CREATE TABLE IF NOT EXISTS activity (
        id                         INTEGER PRIMARY KEY AUTOINCREMENT,
        name                       TEXT NOT NULL,
        flow_gal_per_min           REAL,
        duration_min               REAL,
        events_per_day_per_person  REAL,
        gal_per_unit               REAL,
        grey_pct                   REAL NOT NULL DEFAULT 0,
        black_pct                  REAL NOT NULL DEFAULT 0,
        uses_shower_mult           INTEGER NOT NULL DEFAULT 0,
        uses_sink_mult             INTEGER NOT NULL DEFAULT 0,
        uses_toilet_mult           INTEGER NOT NULL DEFAULT 0,
        uses_adults                INTEGER NOT NULL DEFAULT 0,
        uses_children              INTEGER NOT NULL DEFAULT 0,
        UNIQUE(name)
    );

    -- SECTION 4: Computed daily results
    CREATE TABLE IF NOT EXISTS activity_result (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_name    TEXT NOT NULL,
        daily_fresh_gal  REAL NOT NULL,
        grey_added_gal   REAL NOT NULL,
        black_added_gal  REAL NOT NULL,
        fresh_attrib_pct REAL NOT NULL
    );

    -- SECTION 4: Daily usage per activity per day with drift
    CREATE TABLE IF NOT EXISTS daily_usage_by_day (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_name    TEXT NOT NULL,
        day_num          INTEGER NOT NULL,
        fresh_gal        REAL NOT NULL,
        grey_gal         REAL NOT NULL,
        black_gal        REAL NOT NULL,
        drift_factor     REAL NOT NULL DEFAULT 1.0
    );

    -- SECTION 5: Tank Projections
    CREATE TABLE IF NOT EXISTS tank_projection (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        tank             TEXT NOT NULL,
        capacity_gal     REAL NOT NULL,
        current_gal      REAL NOT NULL,
        daily_delta_gal  REAL NOT NULL,
        days_remaining   REAL NOT NULL,
        status           TEXT NOT NULL
    );

    -- SECTION 5: Stability Score
    CREATE TABLE IF NOT EXISTS stability_score (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        limiting_tank  TEXT NOT NULL,
        limiting_days  REAL NOT NULL,
        target_days    REAL NOT NULL,
        score_pct      REAL NOT NULL,
        status         TEXT NOT NULL,
        fresh_days     REAL NOT NULL DEFAULT 0,
        grey_days      REAL NOT NULL DEFAULT 0,
        black_days     REAL NOT NULL DEFAULT 0
    );
    """)

    # Index for fast per-day, per-activity lookups in realtime endpoint
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_usage_activity_day
        ON daily_usage_by_day (activity_name, day_num)
    """)

    conn.commit()


# ── Migration system ──────────────────────────────────────────────────────────

# Each migration is (version: int, sql: str).
# Append new entries here; never edit existing ones.
_MIGRATIONS: list[tuple[int, str]] = [
    # Version 1: initial schema — handled by create_db() above.
    # Future versions go here, e.g.:
    # (2, "ALTER TABLE activity ADD COLUMN notes TEXT"),
]


def migrate_db(conn: sqlite3.Connection) -> None:
    """
    Run any pending schema migrations.
    create_db() must have been called first so schema_version exists.
    """
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
    current = cur.fetchone()[0]

    for version, sql in _MIGRATIONS:
        if version <= current:
            continue
        cur.executescript(sql)
        cur.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (version,)
        )
        conn.commit()

    # Record version 1 if this is a brand-new DB (create_db just ran)
    if current == 0 and _SCHEMA_VERSION >= 1:
        cur.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (1)"
        )
        conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    """
    Safe startup sequence:
      1. Create tables that are missing (never drops existing ones).
      2. Apply any pending migrations.
      3. Seed default rows only into empty tables.

    Replaces the old reset_database() which DROPped everything on every restart.
    """
    create_db(conn)
    migrate_db(conn)
    seed_data(conn)


def reset_database(conn: sqlite3.Connection) -> None:
    """
    Kept for CLI / test use only.
    Drops and recreates all tables, then seeds defaults.
    DO NOT call from the FastAPI lifespan — use init_db() instead.
    """
    cur = conn.cursor()
    cur.executescript("""
        DROP TABLE IF EXISTS schema_version;
        DROP TABLE IF EXISTS user_type;
        DROP TABLE IF EXISTS tank_environment;
        DROP TABLE IF EXISTS behavior_multiplier;
        DROP TABLE IF EXISTS activity;
        DROP TABLE IF EXISTS activity_result;
        DROP TABLE IF EXISTS daily_usage_by_day;
        DROP TABLE IF EXISTS tank_projection;
        DROP TABLE IF EXISTS stability_score;
    """)
    conn.commit()
    create_db(conn)
    migrate_db(conn)
    seed_data(conn)


# ── Seed data (idempotent) ────────────────────────────────────────────────────

def seed_data(conn: sqlite3.Connection) -> None:
    """
    Insert default rows only where the table is empty.
    All inserts use INSERT OR IGNORE so this is safe to call multiple times.
    """
    cur = conn.cursor()

    cur.executemany(
        "INSERT OR IGNORE INTO user_type (name, count, is_child) VALUES (?,?,?)",
        [
            ("Expert",   1, 0),
            ("Typical",  0, 0),
            ("Glamper",  0, 0),
            ("Children", 2, 1),
        ],
    )

    # INSERT OR IGNORE: if a row already exists (any id), skip silently.
    # This prevents duplicate rows and makes the id=1 assumption in PUT safe.
    cur.execute("""
        INSERT OR IGNORE INTO tank_environment
          (id, fresh_capacity_gal, grey_capacity_gal, black_capacity_gal,
           current_fresh_gal,  current_grey_gal,  current_black_gal,
           climate_multiplier, target_autonomy_days, drift, drift_seed,
           alert_threshold, greywater_recycle)
        VALUES (1, 100, 80, 40, 100, 0, 0, 1.0, 5, 0.4, 41, 0.10, 0)
    """)

    cur.executemany(
        "INSERT OR IGNORE INTO behavior_multiplier "
        "(user_type, shower_mult, sink_mult, toilet_mult) VALUES (?,?,?,?)",
        [
            ("Expert",   0.6, 0.7, 1.0),
            ("Typical",  1.0, 1.0, 1.0),
            ("Glamper",  1.5, 1.4, 1.0),
            ("Children", 0.5, 0.6, 0.8),
        ],
    )

    cur.executemany("""
        INSERT OR IGNORE INTO activity
          (name, flow_gal_per_min, duration_min, events_per_day_per_person,
           gal_per_unit, grey_pct, black_pct,
           uses_shower_mult, uses_sink_mult, uses_toilet_mult,
           uses_adults, uses_children)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, [
        ("Shower",              1.9,  5.0, 1.0,  None, 1.0, 0.0, 1, 0, 0, 0, 0),
        ("Kitchen Sink",        1.5,  3.0, 3.0,  None, 1.0, 0.0, 0, 1, 0, 0, 0),
        ("Bathroom Sink",       1.0,  0.5, 4.0,  None, 1.0, 0.0, 0, 1, 0, 0, 0),
        ("Toilet",              None, None, 6.0, 0.6,  0.0, 1.0, 0, 0, 1, 0, 0),
        ("Drinking (Adults)",   None, None, None, 0.7,  0.0, 0.0, 0, 0, 0, 1, 0),
        ("Drinking (Children)", None, None, None, 0.35, 0.0, 0.0, 0, 0, 0, 0, 1),
    ])

    conn.commit()


# ── Drift helper ──────────────────────────────────────────────────────────────

def _drift_multiplier(drift: float, rng: random.Random) -> float:
    """
    Draw a multiplier from a truncated normal distribution using the supplied RNG.

    Centre = 1.0, std = drift / 2.
    Hard clamp to [1 - drift, 1 + drift] to keep it bounded.
    When drift = 0 returns exactly 1.0 (no noise).
    """
    if drift <= 0.0:
        return 1.0
    lo = max(0.0, 1.0 - drift)
    hi = 1.0 + drift
    std = drift / 2.0
    # Rejection-sample until we land inside [lo, hi] (converges very fast)
    for _ in range(50):
        v = rng.gauss(1.0, std)
        if lo <= v <= hi:
            return v
    # Fallback: clamp
    return max(lo, min(hi, rng.gauss(1.0, std)))


# ── Core compute ──────────────────────────────────────────────────────────────

def compute_and_store(conn: sqlite3.Connection):
    """
    Read editable tables, compute all derived results, and write them back.

    This is a pure write of the four computed tables (activity_result,
    daily_usage_by_day, tank_projection, stability_score). It should be
    called explicitly after user input changes — NOT on every GET request.

    Returns (eff_shower, eff_sink, eff_toilet) for CLI display convenience.
    """
    cur = conn.cursor()

    # ── Load people
    cur.execute("SELECT name, count, is_child FROM user_type")
    users        = cur.fetchall()
    adults_total = sum(r[1] for r in users if r[2] == 0)
    children     = next((r[1] for r in users if r[2] == 1), 0)

    # ── Load environment
    cur.execute("""
        SELECT fresh_capacity_gal, grey_capacity_gal, black_capacity_gal,
               current_fresh_gal, current_grey_gal, current_black_gal,
               climate_multiplier, target_autonomy_days, drift, drift_seed, greywater_recycle
        FROM tank_environment LIMIT 1
    """)
    row = cur.fetchone()
    (fresh_cap, grey_cap, black_cap,
     cur_fresh, cur_grey, cur_black,
     climate_mult, target_days, drift, drift_seed, greywater_recycle) = row

    # Per-cell RNG factory
    def make_rng(name: str, day: int) -> random.Random:
        if drift_seed is not None:
            return random.Random(hash((int(drift_seed), name, day)))
        return random.Random()

    # ── Section 3: Effective multipliers via SUMPRODUCT
    cur.execute("SELECT user_type, shower_mult, sink_mult, toilet_mult FROM behavior_multiplier")
    mults     = {r[0]: r[1:] for r in cur.fetchall()}
    count_map = {r[0]: r[1] for r in users}

    eff_shower = sum(count_map.get(ut, 0) * mults[ut][0] for ut in mults)
    eff_sink   = sum(count_map.get(ut, 0) * mults[ut][1] for ut in mults)
    eff_toilet = sum(count_map.get(ut, 0) * mults[ut][2] for ut in mults)

    # ── Section 4: Baseline daily fresh per activity
    cur.execute("""
        SELECT name, flow_gal_per_min, duration_min, events_per_day_per_person,
               gal_per_unit, grey_pct, black_pct,
               uses_shower_mult, uses_sink_mult, uses_toilet_mult,
               uses_adults, uses_children
        FROM activity
    """)

    computed = []
    for (name, flow, dur, events, gal_unit,
         grey_pct, black_pct, sh, sk, tl, ad, ch) in cur.fetchall():

        if sh:
            fresh = eff_shower * flow * dur * events
        elif sk:
            fresh = eff_sink   * flow * dur * events
        elif tl:
            fresh = eff_toilet * gal_unit * events
        elif ad:
            fresh = adults_total * gal_unit * climate_mult
        elif ch:
            fresh = children     * gal_unit * climate_mult
        else:
            fresh = 0.0

        computed.append((name, fresh, grey_pct, black_pct))

    total_fresh = sum(c[1] for c in computed)
    total_grey  = sum(c[1] * c[2] for c in computed)
    total_black = sum(c[1] * c[3] for c in computed)

    # ── Greywater recycling: steady-state daily savings
    toilet_fresh_baseline = next((c[1] for c in computed if c[0] == "Toilet"), 0.0)
    grey_recycled_per_day = min(toilet_fresh_baseline, total_grey) if greywater_recycle else 0.0
    total_fresh_eff = total_fresh - grey_recycled_per_day
    total_grey_eff  = total_grey  - grey_recycled_per_day

    # ── Store activity_result
    cur.execute("DELETE FROM activity_result")
    for name, fresh, grey_pct, black_pct in computed:
        if greywater_recycle and name == "Toilet":
            eff_fresh   = max(0.0, fresh - grey_recycled_per_day)
            grey_added  = eff_fresh * grey_pct
            black_added = fresh * black_pct
        else:
            eff_fresh   = fresh
            grey_added  = fresh * grey_pct
            black_added = fresh * black_pct
        attrib = (eff_fresh / total_fresh_eff * 100) if total_fresh_eff > 0 else 0
        cur.execute("""
            INSERT INTO activity_result
              (activity_name, daily_fresh_gal, grey_added_gal,
               black_added_gal, fresh_attrib_pct)
            VALUES (?,?,?,?,?)
        """, (name,
              round(eff_fresh, 4),
              round(grey_added, 4),
              round(black_added, 4),
              round(attrib, 2)))

    # ── Store daily_usage_by_day with per-day drift
    cur.execute("DELETE FROM daily_usage_by_day")
    target_days_int = max(1, int(target_days))

    for name, fresh, grey_pct, black_pct in computed:
        for day in range(1, target_days_int + 1):
            factor = _drift_multiplier(drift, make_rng(name, day))
            drifted_fresh = fresh * factor
            cur.execute("""
                INSERT INTO daily_usage_by_day
                  (activity_name, day_num, fresh_gal, grey_gal, black_gal, drift_factor)
                VALUES (?,?,?,?,?,?)
            """, (
                name,
                day,
                round(drifted_fresh, 4),
                round(drifted_fresh * grey_pct, 4),
                round(drifted_fresh * black_pct, 4),
                round(factor, 4),
            ))

    # ── Section 5: Tank projections
    def safe_days(numerator, rate):
        return (numerator / rate) if rate > 0 else math.inf

    def fmt(d):
        return round(d, 2) if d < math.inf else 9999.0

    d_fresh = safe_days(cur_fresh,             total_fresh_eff)
    d_grey  = safe_days(grey_cap  - cur_grey,  total_grey_eff)
    d_black = safe_days(black_cap - cur_black, total_black)

    def status_fresh(d):
        if d >= target_days:         return "✓"
        elif d >= target_days * 0.5: return "⚠️  Low"
        else:                        return "🔴 Critical"

    def status_waste(d):
        if d >= target_days:         return "✓"
        elif d >= target_days * 0.5: return "⚠️  Getting Full"
        else:                        return "🔴 Dump Soon!"

    cur.execute("DELETE FROM tank_projection")
    cur.executemany("""
        INSERT INTO tank_projection
          (tank, capacity_gal, current_gal, daily_delta_gal, days_remaining, status)
        VALUES (?,?,?,?,?,?)
    """, [
        ("Fresh", fresh_cap, cur_fresh, -total_fresh_eff,
         fmt(d_fresh), status_fresh(fmt(d_fresh))),
        ("Grey",  grey_cap,  cur_grey,  +total_grey_eff,
         fmt(d_grey),  status_waste(fmt(d_grey))),
        ("Black", black_cap, cur_black, +total_black,
         fmt(d_black), status_waste(fmt(d_black))),
    ])

    # ── Stability Score
    min_days = min(fmt(d_fresh), fmt(d_grey), fmt(d_black))
    score    = min(min_days / target_days, 1.0) * 100
    limiting = (
        "Fresh" if fmt(d_fresh) <= fmt(d_grey) and fmt(d_fresh) <= fmt(d_black)
        else ("Grey" if fmt(d_grey) <= fmt(d_black) else "Black")
    )

    if score >= 80:
        stability_status = "On track"
    elif score >= 50:
        stability_status = "Needs attention"
    else:
        stability_status = "Not supported"

    cur.execute("DELETE FROM stability_score")
    cur.execute("""
        INSERT INTO stability_score
          (limiting_tank, limiting_days, target_days, score_pct, status,
           fresh_days, grey_days, black_days)
        VALUES (?,?,?,?,?,?,?,?)
    """, (limiting, round(min_days, 2), target_days, round(score, 1), stability_status,
          round(fmt(d_fresh), 2), round(fmt(d_grey), 2), round(fmt(d_black), 2)))

    conn.commit()
    return eff_shower, eff_sink, eff_toilet


# ── CLI display ───────────────────────────────────────────────────────────────

SEP  = "─" * 66
SEP2 = "═" * 66


def print_results(conn: sqlite3.Connection, effs):
    eff_shower, eff_sink, eff_toilet = effs
    cur = conn.cursor()

    print(SEP2)
    print("  💧  WATER INTELLIGENCE ENGINE v2 — SIMULATION RESULTS")
    print(SEP2)

    # ── Section 1
    print("\n📋  SECTION 1 — PEOPLE INPUTS")
    print(f"  {'User Type':<20} {'Count':>6}  Role")
    print(f"  {SEP}")
    cur.execute("SELECT name, count, is_child FROM user_type ORDER BY id")
    adults_total = 0
    for name, count, is_child in cur.fetchall():
        role = "child" if is_child else "adult sub-type"
        print(f"  {name:<20} {count:>6}  {role}")
        if not is_child:
            adults_total += count
    print(f"  {'─'*40}")
    print(f"  {'Adults Total (auto)':<20} {adults_total:>6}  = Expert + Typical + Glamper")

    # ── Section 2
    print(f"\n🛢️   SECTION 2 — TANK & ENVIRONMENT")
    cur.execute("SELECT * FROM tank_environment LIMIT 1")
    row = cur.fetchone()
    labels = ["Fresh Tank Capacity", "Grey Tank Capacity",  "Black Tank Capacity",
              "Current Fresh Level", "Current Grey Level",  "Current Black Level",
              "Climate Multiplier",  "Target Autonomy Days", "Drift"]
    units  = ["gal", "gal", "gal", "gal", "gal", "gal", "×", "days", "0–1"]
    for i, (lbl, unit) in enumerate(zip(labels, units)):
        print(f"  {lbl:<26} {row[i+1]:>8.2f}  {unit}")

    # ── Section 3
    print(f"\n🧠  SECTION 3 — BEHAVIOR MULTIPLIERS")
    print(f"  {'User Type':<12} {'Count':>6}  {'Shower':>8}  {'Sink':>8}  {'Toilet':>8}")
    print(f"  {'─'*50}")
    cur2 = conn.cursor()
    cur2.execute("SELECT name, count FROM user_type")
    count_map = {r[0]: r[1] for r in cur2.fetchall()}
    cur.execute("SELECT user_type, shower_mult, sink_mult, toilet_mult FROM behavior_multiplier")
    for ut, sh, sk, tl in cur.fetchall():
        print(f"  {ut:<12} {count_map.get(ut,0):>6}  {sh:>8.1f}  {sk:>8.1f}  {tl:>8.1f}")
    print(f"  {'─'*50}")
    print(f"  {'Effective':<12} {'':>6}  {eff_shower:>8.2f}  "
          f"{eff_sink:>8.2f}  {eff_toilet:>8.2f}  ← SUMPRODUCT")

    # ── Section 4
    print(f"\n⚡  SECTION 4 — ACTIVITY ENGINE (baseline)")
    print(f"  {'Activity':<24} {'Fresh/day':>10}  {'Grey/day':>9}  "
          f"{'Black/day':>10}  {'Attrib%':>8}")
    print(f"  {'─'*66}")
    cur.execute("""SELECT activity_name, daily_fresh_gal, grey_added_gal,
                          black_added_gal, fresh_attrib_pct
                   FROM activity_result""")
    rows = cur.fetchall()
    for name, fresh, grey, black, attrib in rows:
        print(f"  {name:<24} {fresh:>10.2f}  {grey:>9.2f}  "
              f"{black:>10.2f}  {attrib:>7.1f}%")
    tf = sum(r[1] for r in rows)
    tg = sum(r[2] for r in rows)
    tb = sum(r[3] for r in rows)
    print(f"  {'─'*66}")
    print(f"  {'TOTAL':<24} {tf:>10.2f}  {tg:>9.2f}  {tb:>10.2f}  {'100.0%':>8}")

    # ── Section 5 — Projections
    print(f"\n🔋  SECTION 5 — TANK PROJECTIONS")
    print(f"  {'Tank':<8} {'Capacity':>9}  {'Current':>8}  "
          f"{'Daily Δ':>9}  {'Days Left':>10}  Status")
    print(f"  {'─'*66}")
    cur.execute("""SELECT tank, capacity_gal, current_gal, daily_delta_gal,
                          days_remaining, status
                   FROM tank_projection""")
    for tank, cap, curr, delta, days, status in cur.fetchall():
        days_str = f"{days:.2f}" if days < 9000 else "∞"
        print(f"  {tank:<8} {cap:>9.1f}  {curr:>8.1f}  "
              f"{delta:>+9.2f}  {days_str:>10}  {status}")

    # ── Stability Score
    print(f"\n🎯  STABILITY SCORE")
    print(f"  {'─'*45}")
    cur.execute("""SELECT limiting_tank, limiting_days, target_days,
                          score_pct, status
                   FROM stability_score""")
    lt, ld, td, sc, st = cur.fetchone()
    print(f"  Limiting Tank   : {lt}")
    print(f"  Limiting Days   : {ld:.2f} days")
    print(f"  Target Days     : {td:.0f} days")
    print(f"  Stability Score : {sc:.1f} / 100")
    print(f"  Status          : {st}")
    print(SEP2)

    # ── Table inventory
    print("\n📂  SQLITE TABLES")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for (tname,) in cur.fetchall():
        cur2.execute(f"SELECT COUNT(*) FROM {tname}")
        n = cur2.fetchone()[0]
        print(f"  • {tname:<28} ({n} row{'s' if n != 1 else ''})")
    print(SEP2)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    # CLI: always start fresh for a clean reproducible printout.
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_connection(DB_PATH)
    reset_database(conn)          # full wipe + seed for CLI runs
    effs = compute_and_store(conn)
    print_results(conn, effs)
    conn.close()