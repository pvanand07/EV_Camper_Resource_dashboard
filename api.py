"""
FastAPI backend for Water Intelligence Engine v2.
Exposes editable inputs and computed results.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

import water_model

app = FastAPI(title="Water Intelligence Engine v2 API")


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


def _cors_allow_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    @field_validator("count", "is_child", mode="before")
    @classmethod
    def empty_str_int_to_zero(cls, v):
        if v == "" or v is None:
            return 0
        return v


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
    alert_threshold: float = 0.10  # fraction; e.g. 0.10 = alert when usage >10% above baseline
    greywater_recycle: int = 0  # 1 = redirect previous-day grey into toilet flushing


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
            "alert_threshold":      row["alert_threshold"],
            "greywater_recycle":    row["greywater_recycle"],
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
                    climate_multiplier = ?, target_autonomy_days = ?, drift = ?, drift_seed = ?,
                    alert_threshold = ?, greywater_recycle = ?
                WHERE id = 1
            """, (
                t.fresh_capacity_gal, t.grey_capacity_gal, t.black_capacity_gal,
                t.current_fresh_gal, t.current_grey_gal, t.current_black_gal,
                t.climate_multiplier, t.target_autonomy_days, t.drift, t.drift_seed,
                t.alert_threshold, t.greywater_recycle,
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
        cur.execute("SELECT name, count FROM user_type")  # include children
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

        # Environment values for display
        cur.execute("SELECT target_autonomy_days, drift, drift_seed, greywater_recycle FROM tank_environment LIMIT 1")
        row_te = cur.fetchone()
        target_days        = int(row_te[0])   if row_te else 5
        drift_val          = float(row_te[1]) if row_te else 0.0
        seed_val           = row_te[2]        if row_te else None
        greywater_recycle  = bool(row_te[3])  if row_te else False

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
            "greywater_recycle": greywater_recycle,
            "tank_projections": tank_projections,
            "stability_score": stability_score,
            "heat_ranges": heat_ranges,
            "heat_groups": heat_groups,
        }


# ─── Realtime: per-day stats and 10% baseline alerts ─────────────────────────

def _realtime_baseline(activity_results: list) -> dict:
    """Baseline daily totals from activity_result (deterministic)."""
    fresh = sum(r.get("daily_fresh_gal") or 0 for r in activity_results)
    grey = sum(r.get("grey_added_gal") or 0 for r in activity_results)
    black = sum(r.get("black_added_gal") or 0 for r in activity_results)
    return {"fresh_gal": round(fresh, 2), "grey_gal": round(grey, 2), "black_gal": round(black, 2)}


def _realtime_day_totals(raw_rows: list, day_num: int) -> dict:
    """Sum fresh/grey/black for a given day from daily_usage_by_day rows."""
    fresh = sum(r["fresh_gal"] for r in raw_rows if r["day_num"] == day_num)
    grey = sum(r["grey_gal"] for r in raw_rows if r["day_num"] == day_num)
    black = sum(r["black_gal"] for r in raw_rows if r["day_num"] == day_num)
    return {"fresh_gal": round(fresh, 2), "grey_gal": round(grey, 2), "black_gal": round(black, 2)}


def _realtime_day_activities(raw_rows: list, day_num: int) -> list:
    """Per-activity usage for a given day."""
    return [
        {
            "activity_name": r["activity_name"],
            "fresh_gal": round(r["fresh_gal"], 2),
            "grey_gal": round(r["grey_gal"], 2),
            "black_gal": round(r["black_gal"], 2),
            "drift_factor": round(r["drift_factor"], 3),
        }
        for r in raw_rows
        if r["day_num"] == day_num
    ]


@app.get("/api/realtime")
def get_realtime():
    """Realtime view: per-day stats, daily activities, and alerts when usage > 10% above baseline."""
    with get_conn() as conn:
        ensure_initialized(conn)
        water_model.compute_and_store(conn)
        cur = conn.cursor()

        cur.execute("""
            SELECT target_autonomy_days, fresh_capacity_gal, grey_capacity_gal, black_capacity_gal,
                   current_fresh_gal, current_grey_gal, current_black_gal, alert_threshold,
                   greywater_recycle
            FROM tank_environment LIMIT 1
        """)
        row = cur.fetchone()
        target_days          = max(1, int(row[0])) if row else 5
        fresh_cap            = float(row[1]) if row else 100
        grey_cap             = float(row[2]) if row else 80
        black_cap            = float(row[3]) if row else 40
        cur_fresh            = float(row[4]) if row else 100
        cur_grey             = float(row[5]) if row else 0
        cur_black            = float(row[6]) if row else 0
        alert_threshold_frac = float(row[7]) if row and row[7] is not None else 0.10
        greywater_recycle    = bool(row[8])  if row else False

        tank_capacities = {
            "fresh_gal": round(fresh_cap, 2),
            "grey_gal": round(grey_cap, 2),
            "black_gal": round(black_cap, 2),
        }

        cur.execute("""
            SELECT activity_name, daily_fresh_gal, grey_added_gal, black_added_gal
            FROM activity_result
        """)
        activity_results = [dict(r) for r in cur.fetchall()]
        baseline = _realtime_baseline(activity_results)

        cur.execute("""
            SELECT activity_name, day_num, fresh_gal, grey_gal, black_gal, drift_factor
            FROM daily_usage_by_day ORDER BY activity_name, day_num
        """)
        raw_rows = [dict(r) for r in cur.fetchall()]

        # Build daily_usage_by_day (pivot) for heatmap reuse
        by_activity = {}
        for r in raw_rows:
            name, day, fresh, grey, black, factor = (
                r["activity_name"], r["day_num"], r["fresh_gal"], r["grey_gal"], r["black_gal"], r["drift_factor"]
            )
            if name not in by_activity:
                by_activity[name] = {"activity": name}
            by_activity[name][f"fresh_{day}"] = round(fresh, 2)
            by_activity[name][f"grey_{day}"] = round(grey, 2)
            by_activity[name][f"back_{day}"] = round(black, 2)
            by_activity[name][f"factor_{day}"] = round(factor, 3)
        order = {r["activity_name"]: i for i, r in enumerate(activity_results)}
        daily_usage_by_day = sorted(by_activity.values(), key=lambda x: order.get(x["activity"], 999))

        heat_ranges = _heatmap_ranges(daily_usage_by_day, target_days)
        heat_groups = _heatmap_groups(daily_usage_by_day)

        # Cumulative tank levels per day (capped to 0 and capacity)
        def _cap_fresh(gal):
            return round(max(0, min(fresh_cap, gal)), 2)

        def _cap_grey(gal):
            return round(max(0, min(grey_cap, gal)), 2)

        def _cap_black(gal):
            return round(max(0, min(black_cap, gal)), 2)

        running_fresh = cur_fresh
        running_grey = cur_grey
        running_black = cur_black

        # Pre-build per-day toilet fresh lookup for greywater recycling calculations
        toilet_fresh_by_day = {
            r["day_num"]: r["fresh_gal"]
            for r in raw_rows if r["activity_name"] == "Toilet"
        }

        # Per-day summaries, tank levels, and alerts (usage above baseline by alert_threshold fraction)
        threshold = 1.0 + alert_threshold_frac
        days = []
        prev_day_grey_total = 0.0
        for day_num in range(1, target_days + 1):
            totals = _realtime_day_totals(raw_rows, day_num)
            activities = _realtime_day_activities(raw_rows, day_num)

            # Greywater recycling: previous day's grey offsets toilet fresh draw on days 2+
            grey_recycled = 0.0
            if greywater_recycle and day_num > 1:
                toilet_fresh_today = toilet_fresh_by_day.get(day_num, 0.0)
                grey_recycled = min(toilet_fresh_today, prev_day_grey_total)

            # Apply day's usage: fresh decreases (less if recycling), grey fills then drains by recycled amount
            running_fresh = _cap_fresh(running_fresh - totals["fresh_gal"] + grey_recycled)
            running_grey  = _cap_grey(running_grey  + totals["grey_gal"]   - grey_recycled)
            running_black = _cap_black(running_black + totals["black_gal"])
            prev_day_grey_total = totals["grey_gal"]
            tank_levels = {
                "fresh_gal": running_fresh,
                "grey_gal": running_grey,
                "black_gal": running_black,
            }

            alert_fresh = baseline["fresh_gal"] > 0 and totals["fresh_gal"] > baseline["fresh_gal"] * threshold
            alert_grey = baseline["grey_gal"] > 0 and totals["grey_gal"] > baseline["grey_gal"] * threshold
            alert_black = baseline["black_gal"] > 0 and totals["black_gal"] > baseline["black_gal"] * threshold
            alert = alert_fresh or alert_grey or alert_black

            def _pct_above(baseline_gal, actual_gal):
                if baseline_gal <= 0:
                    return 0
                return round((actual_gal / baseline_gal - 1) * 100)

            alerts_list = []
            stream_labels = {"fresh": "Fresh", "grey": "Grey", "black": "Black"}
            if alert_fresh:
                pct = _pct_above(baseline["fresh_gal"], totals["fresh_gal"])
                alerts_list.append({
                    "stream": "fresh",
                    "message": f"{stream_labels['fresh']} water usage is {pct}% more than usual",
                })
            if alert_grey:
                pct = _pct_above(baseline["grey_gal"], totals["grey_gal"])
                alerts_list.append({
                    "stream": "grey",
                    "message": f"{stream_labels['grey']} water usage is {pct}% more than usual",
                })
            if alert_black:
                pct = _pct_above(baseline["black_gal"], totals["black_gal"])
                alerts_list.append({
                    "stream": "black",
                    "message": f"{stream_labels['black']} water usage is {pct}% more than usual",
                })

            days.append({
                "day_num": int(day_num),
                "stats": totals,
                "baseline": baseline,
                "activities": activities,
                "tank_levels": tank_levels,
                "alert": alert,
                "alert_fresh": alert_fresh,
                "alert_grey": alert_grey,
                "alert_black": alert_black,
                "alerts": alerts_list,
                "grey_recycled_gal": round(grey_recycled, 2),
            })
    return {
        "target_days": target_days,
        "baseline": baseline,
        "tank_capacities": tank_capacities,
        "days": days,
        "daily_usage_by_day": daily_usage_by_day,
        "heat_ranges": heat_ranges,
        "heat_groups": heat_groups,
        "greywater_recycle": greywater_recycle,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)