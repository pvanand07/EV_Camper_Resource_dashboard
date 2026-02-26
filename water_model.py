"""
Water Intelligence Engine v2
Pure stdlib Python (sqlite3) mirroring a SQLModel table architecture.
Maps directly to the Water_Model_v2 unified architecture (5 sections).
"""

import sqlite3
import math
import os
import sys
import random

# Ensure UTF-8 output on Windows so emoji/box-drawing characters print correctly
if os.name == "nt" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "water_intelligence.db")


def create_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript("""
    DROP TABLE IF EXISTS user_type;
    DROP TABLE IF EXISTS tank_environment;
    DROP TABLE IF EXISTS behavior_multiplier;
    DROP TABLE IF EXISTS activity;
    DROP TABLE IF EXISTS activity_result;
    DROP TABLE IF EXISTS daily_usage_by_day;
    DROP TABLE IF EXISTS tank_projection;
    DROP TABLE IF EXISTS stability_score;

    -- SECTION 1: People Inputs (UNIQUE so seed_data cannot insert duplicates if run twice, e.g. concurrent init)
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
        drift                REAL NOT NULL DEFAULT 0.0,  -- 0=none, 1=max. controls per-day normal drift
        drift_seed           INTEGER,                    -- NULL = random each run, integer = locked seed
        alert_threshold      REAL NOT NULL DEFAULT 0.10  -- fraction; e.g. 0.10 = alert when usage >10% above baseline
    );

    -- SECTION 3: Behavior Multipliers per user type
    CREATE TABLE IF NOT EXISTS behavior_multiplier (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_type    TEXT NOT NULL,
        shower_mult  REAL NOT NULL,
        sink_mult    REAL NOT NULL,
        toilet_mult  REAL NOT NULL
    );

    -- SECTION 4: Activity Engine — base parameters (editable)
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
        uses_children              INTEGER NOT NULL DEFAULT 0
    );

    -- SECTION 4: Activity Engine — computed daily results (deterministic baseline)
    CREATE TABLE IF NOT EXISTS activity_result (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_name    TEXT NOT NULL,
        daily_fresh_gal  REAL NOT NULL,
        grey_added_gal   REAL NOT NULL,
        black_added_gal  REAL NOT NULL,
        fresh_attrib_pct REAL NOT NULL
    );

    -- SECTION 4: Daily usage split across target days (per activity, per day, with drift applied)
    CREATE TABLE IF NOT EXISTS daily_usage_by_day (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_name    TEXT NOT NULL,
        day_num          INTEGER NOT NULL,
        fresh_gal        REAL NOT NULL,
        grey_gal         REAL NOT NULL,
        black_gal        REAL NOT NULL,
        drift_factor     REAL NOT NULL DEFAULT 1.0   -- the drawn multiplier for transparency
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
        rating         TEXT NOT NULL
    );
    """)
    conn.commit()


def seed_data(conn: sqlite3.Connection):
    cur = conn.cursor()

    cur.executemany(
        "INSERT OR IGNORE INTO user_type (name, count, is_child) VALUES (?,?,?)",
        [
            ("Expert",   1, 0),
            ("Typical",  0, 0),
            ("Glamper",  0, 0),
            ("Children", 2, 1),
        ]
    )

    cur.execute("""
        INSERT INTO tank_environment
          (fresh_capacity_gal, grey_capacity_gal, black_capacity_gal,
           current_fresh_gal,  current_grey_gal,  current_black_gal,
           climate_multiplier, target_autonomy_days, drift, drift_seed, alert_threshold)
        VALUES (100, 80, 40, 100, 0, 0, 1.0, 5, 0.4, 41, 0.10)
    """)

    cur.executemany(
        "INSERT INTO behavior_multiplier "
        "(user_type, shower_mult, sink_mult, toilet_mult) VALUES (?,?,?,?)",
        [
            ("Expert",  0.6, 0.7, 1.0),
            ("Typical", 1.0, 1.0, 1.0),
            ("Glamper", 1.5, 1.4, 1.0),
        ]
    )

    cur.executemany("""
        INSERT INTO activity
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


def _migrate(conn: sqlite3.Connection):
    """Add missing columns to existing DBs without dropping tables."""
    cur = conn.cursor()

    # daily_usage_by_day table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_usage_by_day (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_name    TEXT NOT NULL,
            day_num          INTEGER NOT NULL,
            fresh_gal        REAL NOT NULL,
            grey_gal         REAL NOT NULL,
            black_gal        REAL NOT NULL,
            drift_factor     REAL NOT NULL DEFAULT 1.0
        )
    """)

    # drift_factor column on existing daily_usage_by_day
    try:
        cur.execute("ALTER TABLE daily_usage_by_day ADD COLUMN drift_factor REAL NOT NULL DEFAULT 1.0")
    except sqlite3.OperationalError:
        pass  # already exists

    # drift column on tank_environment
    try:
        cur.execute("ALTER TABLE tank_environment ADD COLUMN drift REAL NOT NULL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass  # already exists

    # drift_seed column on tank_environment
    try:
        cur.execute("ALTER TABLE tank_environment ADD COLUMN drift_seed INTEGER")
    except sqlite3.OperationalError:
        pass  # already exists

    # alert_threshold column on tank_environment (fraction; 0.10 = 10%)
    try:
        cur.execute("ALTER TABLE tank_environment ADD COLUMN alert_threshold REAL NOT NULL DEFAULT 0.10")
    except sqlite3.OperationalError:
        pass  # already exists

    # Default current_fresh_gal to 100 if it was seeded as 0
    cur.execute("UPDATE tank_environment SET current_fresh_gal = 100 WHERE id = 1 AND current_fresh_gal = 0")

    conn.commit()


def _drift_multiplier(drift: float, rng: random.Random) -> float:
    """
    Draw a multiplier from a truncated normal distribution using the supplied RNG.

    Centre = 1.0, std = drift / 2
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


def compute_and_store(conn: sqlite3.Connection):
    cur = conn.cursor()
    _migrate(conn)

    # ── Load people
    cur.execute("SELECT name, count, is_child FROM user_type")
    users        = cur.fetchall()
    adults_total = sum(r[1] for r in users if r[2] == 0)
    children     = next((r[1] for r in users if r[2] == 1), 0)

    # ── Load environment (including drift)
    cur.execute("SELECT * FROM tank_environment LIMIT 1")
    row = cur.fetchone()
    (_, fresh_cap, grey_cap, black_cap,
     cur_fresh, cur_grey, cur_black,
     climate_mult, target_days, drift, drift_seed) = row

    # Per-cell RNG factory.
    # When drift_seed is set: each (activity, day) gets its own Random instance seeded
    # by hash((drift_seed, name, day)) — fully reproducible regardless of iteration order.
    # When drift_seed is None: each cell gets a fresh unseeded Random() — random every run.
    def make_rng(name: str, day: int) -> random.Random:
        if drift_seed is not None:
            return random.Random(hash((int(drift_seed), name, day)))
        return random.Random()

    # ── Section 3: Effective multipliers via SUMPRODUCT
    cur.execute("SELECT user_type, shower_mult, sink_mult, toilet_mult FROM behavior_multiplier")
    mults     = {r[0]: r[1:] for r in cur.fetchall()}
    count_map = {r[0]: r[1] for r in users if r[2] == 0}

    eff_shower = sum(count_map[ut] * mults[ut][0] for ut in count_map)
    eff_sink   = sum(count_map[ut] * mults[ut][1] for ut in count_map)
    eff_toilet = sum(count_map[ut] * mults[ut][2] for ut in count_map)

    # ── Section 4: Baseline daily fresh per activity (deterministic)
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

    # ── Store ActivityResult (always deterministic baseline — no drift here)
    cur.execute("DELETE FROM activity_result")
    for name, fresh, grey_pct, black_pct in computed:
        attrib = (fresh / total_fresh * 100) if total_fresh > 0 else 0
        cur.execute("""
            INSERT INTO activity_result
              (activity_name, daily_fresh_gal, grey_added_gal,
               black_added_gal, fresh_attrib_pct)
            VALUES (?,?,?,?,?)
        """, (name,
              round(fresh, 4),
              round(fresh * grey_pct, 4),
              round(fresh * black_pct, 4),
              round(attrib, 2)))

    total_grey  = sum(c[1] * c[2] for c in computed)
    total_black = sum(c[1] * c[3] for c in computed)

    # ── Daily usage split across target days with per-day, per-activity drift
    # Each (activity × day) gets an independently drawn drift multiplier from
    # N(1.0, (drift/2)²) truncated to [1-drift, 1+drift].
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

    # ── Section 5: Tank projections (use deterministic baseline totals)
    def safe_days(numerator, rate):
        return (numerator / rate) if rate > 0 else math.inf

    def fmt(d):
        return round(d, 2) if d < math.inf else 9999.0

    d_fresh = safe_days(cur_fresh,              total_fresh)
    d_grey  = safe_days(grey_cap  - cur_grey,   total_grey)
    d_black = safe_days(black_cap - cur_black,  total_black)

    def status_fresh(d):
        if d >= target_days:         return "✅ On Track"
        elif d >= target_days * 0.5: return "⚠️  Low"
        else:                         return "🔴 Critical"

    def status_waste(d):
        if d >= target_days:         return "✅ On Track"
        elif d >= target_days * 0.5: return "⚠️  Getting Full"
        else:                         return "🔴 Dump Soon!"

    cur.execute("DELETE FROM tank_projection")
    cur.executemany("""
        INSERT INTO tank_projection
          (tank, capacity_gal, current_gal, daily_delta_gal, days_remaining, status)
        VALUES (?,?,?,?,?,?)
    """, [
        ("Fresh", fresh_cap, cur_fresh, -total_fresh,
         fmt(d_fresh), status_fresh(fmt(d_fresh))),
        ("Grey",  grey_cap,  cur_grey,  +total_grey,
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

    if   score >= 100: rating = "🟢 Full Autonomy"
    elif score >= 70:  rating = "🟡 Good"
    elif score >= 40:  rating = "🟠 Marginal"
    else:               rating = "🔴 Insufficient"

    cur.execute("DELETE FROM stability_score")
    cur.execute("""
        INSERT INTO stability_score
          (limiting_tank, limiting_days, target_days, score_pct, rating)
        VALUES (?,?,?,?,?)
    """, (limiting, round(min_days, 2), target_days, round(score, 1), rating))

    conn.commit()
    return eff_shower, eff_sink, eff_toilet


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
    units  = ["gal","gal","gal","gal","gal","gal","×","days","0–1"]
    for i, (lbl, unit) in enumerate(zip(labels, units)):
        print(f"  {lbl:<26} {row[i+1]:>8.2f}  {unit}")

    # ── Section 3
    print(f"\n🧠  SECTION 3 — BEHAVIOR MULTIPLIERS")
    print(f"  {'User Type':<12} {'Count':>6}  {'Shower':>8}  {'Sink':>8}  {'Toilet':>8}")
    print(f"  {'─'*50}")
    cur2 = conn.cursor()
    cur2.execute("SELECT name, count FROM user_type WHERE is_child=0")
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
                          score_pct, rating
                   FROM stability_score""")
    lt, ld, td, sc, rt = cur.fetchone()
    print(f"  Limiting Tank   : {lt}")
    print(f"  Limiting Days   : {ld:.2f} days")
    print(f"  Target Days     : {td:.0f} days")
    print(f"  Stability Score : {sc:.1f} / 100")
    print(f"  Rating          : {rt}")
    print(SEP2)

    # ── Table inventory
    print("\n📂  SQLITE TABLES")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for (tname,) in cur.fetchall():
        cur2.execute(f"SELECT COUNT(*) FROM {tname}")
        n = cur2.fetchone()[0]
        print(f"  • {tname:<28} ({n} row{'s' if n != 1 else ''})")
    print(SEP2)


if __name__ == "__main__":
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    create_db(conn)
    seed_data(conn)
    effs = compute_and_store(conn)
    print_results(conn, effs)
    conn.close()