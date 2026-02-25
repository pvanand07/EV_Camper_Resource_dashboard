"""
FastAPI backend for Water Intelligence Engine v2.
Exposes editable inputs and computed results.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import water_model

app = FastAPI(title="Water Intelligence Engine v2 API")


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@contextmanager
def get_conn():
    conn = sqlite3.connect(water_model.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def ensure_initialized(conn: sqlite3.Connection):
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM user_type")
        if cur.fetchone()[0] == 0:
            water_model.create_db(conn)
            water_model.seed_data(conn)
    except sqlite3.OperationalError:
        water_model.create_db(conn)
        water_model.seed_data(conn)
    # Always run migrations so new columns (drift, drift_factor) exist
    # on existing databases before any read or write touches them.
    water_model._migrate(conn)


# ─── Pydantic models ────────────────────────────────────────────────────────

class UserTypeUpdate(BaseModel):
    name: str
    count: int
    is_child: int = 0


class TankEnvironmentUpdate(BaseModel):
    fresh_capacity_gal: float = 100
    grey_capacity_gal: float = 80
    black_capacity_gal: float = 40
    current_fresh_gal: float = 100
    current_grey_gal: float = 0
    current_black_gal: float = 0
    climate_multiplier: float = 1.0
    target_autonomy_days: float = 5
    drift: float = 0.0          # NEW — 0 = deterministic, 1 = max normal drift
    drift_seed: int | None = None  # None = fresh random each run, int = locked seed


class BehaviorMultiplierUpdate(BaseModel):
    user_type: str
    shower_mult: float
    sink_mult: float
    toilet_mult: float


class ActivityUpdate(BaseModel):
    id: int
    name: str
    flow_gal_per_min: float | None
    duration_min: float | None
    events_per_day_per_person: float | None
    gal_per_unit: float | None
    grey_pct: float
    black_pct: float


class InputsUpdate(BaseModel):
    user_types: list[UserTypeUpdate] | None = None
    tank_environment: TankEnvironmentUpdate | None = None
    behavior_multipliers: list[BehaviorMultiplierUpdate] | None = None
    activities: list[ActivityUpdate] | None = None


# ─── Daily Usage Heatmap (backend calculations) ────────────────────────────────

HEATMAP_GROUPS = [
    {"name": "Hygiene", "icon": "🚿", "members": ["Shower", "Bathroom Sink"]},
    {"name": "Kitchen", "icon": "🍳", "members": ["Kitchen Sink"]},
    {"name": "Sanitation", "icon": "🚽", "members": ["Toilet"]},
    {"name": "Drinking", "icon": "💧", "members": ["Drinking (Adults)", "Drinking (Children)"]},
]


def _heatmap_ranges(daily_usage_by_day: list, target_days: int) -> dict:
    """Min/max per stream (fresh, grey, black) across all activities × days."""
    if not daily_usage_by_day or target_days <= 0:
        return {"fresh": {"min": 0, "max": 1}, "grey": {"min": 0, "max": 1}, "back": {"min": 0, "max": 1}}
    days = range(1, int(target_days) + 1)
    streams = ("fresh", "grey", "back")
    out = {s: {"min": float("inf"), "max": float("-inf")} for s in streams}
    for row in daily_usage_by_day:
        for d in days:
            for s in streams:
                v = row.get(f"{s}_{d}", 0) or 0
                if v < out[s]["min"]:
                    out[s]["min"] = v
                if v > out[s]["max"]:
                    out[s]["max"] = v
    for s in streams:
        if out[s]["max"] <= out[s]["min"]:
            out[s]["max"] = out[s]["min"] + 0.001
    return out


def _heatmap_groups(daily_usage_by_day: list) -> list:
    """Group activity rows by HEATMAP_GROUPS for heatmap table."""
    if not daily_usage_by_day:
        return []
    by_name = {r["activity"]: r for r in daily_usage_by_day}
    return [
        {**g, "rows": [by_name[m] for m in g["members"] if m in by_name]}
        for g in HEATMAP_GROUPS
        if any(m in by_name for m in g["members"])
    ]


# ─── API Endpoints ───────────────────────────────────────────────────────────

@app.get("/api/inputs")
def get_inputs():
    with get_conn() as conn:
        ensure_initialized(conn)
        cur = conn.cursor()

        cur.execute("SELECT name, count, is_child FROM user_type ORDER BY id")
        user_types = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM tank_environment LIMIT 1")
        row = cur.fetchone()
        tank_environment = {
            "fresh_capacity_gal":   row["fresh_capacity_gal"],
            "grey_capacity_gal":    row["grey_capacity_gal"],
            "black_capacity_gal":   row["black_capacity_gal"],
            "current_fresh_gal":    row["current_fresh_gal"],
            "current_grey_gal":     row["current_grey_gal"],
            "current_black_gal":    row["current_black_gal"],
            "climate_multiplier":   row["climate_multiplier"],
            "target_autonomy_days": row["target_autonomy_days"],
            "drift":                row["drift"],
            "drift_seed":           row["drift_seed"],
        } if row else None

        cur.execute("SELECT user_type, shower_mult, sink_mult, toilet_mult FROM behavior_multiplier")
        behavior_multipliers = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT id, name, flow_gal_per_min, duration_min, events_per_day_per_person,
                   gal_per_unit, grey_pct, black_pct
            FROM activity ORDER BY id
        """)
        activities = [dict(r) for r in cur.fetchall()]

        return {
            "user_types": user_types,
            "tank_environment": tank_environment,
            "behavior_multipliers": behavior_multipliers,
            "activities": activities,
        }


@app.put("/api/inputs")
def put_inputs(payload: InputsUpdate):
    with get_conn() as conn:
        ensure_initialized(conn)
        cur = conn.cursor()

        if payload.user_types is not None:
            for u in payload.user_types:
                cur.execute(
                    "UPDATE user_type SET count = ? WHERE name = ? AND is_child = ?",
                    (u.count, u.name, u.is_child),
                )

        if payload.tank_environment is not None:
            t = payload.tank_environment
            cur.execute("""
                UPDATE tank_environment SET
                    fresh_capacity_gal = ?, grey_capacity_gal = ?, black_capacity_gal = ?,
                    current_fresh_gal = ?, current_grey_gal = ?, current_black_gal = ?,
                    climate_multiplier = ?, target_autonomy_days = ?, drift = ?, drift_seed = ?
                WHERE id = 1
            """, (
                t.fresh_capacity_gal, t.grey_capacity_gal, t.black_capacity_gal,
                t.current_fresh_gal, t.current_grey_gal, t.current_black_gal,
                t.climate_multiplier, t.target_autonomy_days, t.drift, t.drift_seed,
            ))

        if payload.behavior_multipliers is not None:
            for b in payload.behavior_multipliers:
                cur.execute("""
                    UPDATE behavior_multiplier SET
                        shower_mult = ?, sink_mult = ?, toilet_mult = ?
                    WHERE user_type = ?
                """, (b.shower_mult, b.sink_mult, b.toilet_mult, b.user_type))

        if payload.activities is not None:
            for a in payload.activities:
                cur.execute("""
                    UPDATE activity SET
                        name = ?, flow_gal_per_min = ?, duration_min = ?,
                        events_per_day_per_person = ?, gal_per_unit = ?,
                        grey_pct = ?, black_pct = ?
                    WHERE id = ?
                """, (
                    a.name, a.flow_gal_per_min, a.duration_min,
                    a.events_per_day_per_person, a.gal_per_unit,
                    a.grey_pct, a.black_pct, a.id,
                ))

        conn.commit()

    return {"ok": True}


@app.post("/api/compute")
def compute():
    with get_conn() as conn:
        ensure_initialized(conn)
        water_model.compute_and_store(conn)
    return {"ok": True}


@app.get("/api/results")
def get_results():
    with get_conn() as conn:
        ensure_initialized(conn)
        water_model.compute_and_store(conn)
        cur = conn.cursor()

        cur.execute("SELECT user_type, shower_mult, sink_mult, toilet_mult FROM behavior_multiplier")
        mults = {r["user_type"]: r for r in cur.fetchall()}
        cur.execute("SELECT name, count FROM user_type WHERE is_child = 0")
        count_map = {r["name"]: r["count"] for r in cur.fetchall()}
        eff_shower = sum(count_map.get(ut, 0) * mults[ut]["shower_mult"] for ut in mults)
        eff_sink = sum(count_map.get(ut, 0) * mults[ut]["sink_mult"] for ut in mults)
        eff_toilet = sum(count_map.get(ut, 0) * mults[ut]["toilet_mult"] for ut in mults)

        cur.execute("""
            SELECT activity_name, daily_fresh_gal, grey_added_gal, black_added_gal, fresh_attrib_pct
            FROM activity_result
        """)
        activity_results = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT tank, capacity_gal, current_gal, daily_delta_gal, days_remaining, status
            FROM tank_projection
        """)
        tank_projections = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM stability_score LIMIT 1")
        row = cur.fetchone()
        stability_score = dict(row) if row else None

        # Drift value for display
        cur.execute("SELECT target_autonomy_days, drift, drift_seed FROM tank_environment LIMIT 1")
        row_te = cur.fetchone()
        target_days = int(row_te[0]) if row_te else 5
        drift_val   = float(row_te[1]) if row_te else 0.0
        seed_val    = row_te[2] if row_te else None

        # Daily usage — pivot by activity + include drift_factor per day
        cur.execute("""
            SELECT activity_name, day_num, fresh_gal, grey_gal, black_gal, drift_factor
            FROM daily_usage_by_day ORDER BY activity_name, day_num
        """)
        raw = cur.fetchall()
        by_activity = {}
        for r in raw:
            name, day, fresh, grey, black, factor = r
            if name not in by_activity:
                by_activity[name] = {"activity": name}
            by_activity[name][f"fresh_{day}"]  = round(fresh, 2)
            by_activity[name][f"grey_{day}"]   = round(grey, 2)
            by_activity[name][f"back_{day}"]   = round(black, 2)
            by_activity[name][f"factor_{day}"] = round(factor, 3)

        order = {r["activity_name"]: i for i, r in enumerate(activity_results)}
        daily_usage_by_day = sorted(by_activity.values(), key=lambda x: order.get(x["activity"], 999))

        # Daily Usage Heatmap: ranges and groups computed on backend
        heat_ranges = _heatmap_ranges(daily_usage_by_day, target_days)
        heat_groups = _heatmap_groups(daily_usage_by_day)

        return {
            "effective_multipliers": {"shower": eff_shower, "sink": eff_sink, "toilet": eff_toilet},
            "activity_results": activity_results,
            "daily_usage_by_day": daily_usage_by_day,
            "target_days": target_days,
            "drift": drift_val,
            "drift_seed": seed_val,
            "tank_projections": tank_projections,
            "stability_score": stability_score,
            "heat_ranges": heat_ranges,
            "heat_groups": heat_groups,
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)