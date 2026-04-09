"""
FastAPI backend for Water Intelligence Engine v2.
Exposes editable inputs and computed results.

Changes from original:
- lifespan calls init_db() (migrate + seed) instead of reset_database().
  User data now survives server restarts.
- Shared WAL-mode connection managed via _db_conn / _db_lock so all
  requests use one connection and concurrent writes are serialised.
- get_conn() context manager acquires the lock and yields the shared conn.
- PUT /api/inputs triggers compute_and_store() after saving — GETs no longer do.
- GET /api/results and GET /api/realtime are now pure reads.
- TankEnvironmentUpdate gains Pydantic validators: non-negative gallons,
  current ≤ capacity, drift ∈ [0, 1], climate_multiplier > 0.
- Heatmap pivot key renamed "back" → "black" (was a typo) in both
  get_results() and get_realtime(), and in _heatmap_ranges().
"""

import math
import os
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Generator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator, model_validator

import water_model
from recommended_actions_route import build_recommended_actions, router as recommended_actions_router


# ── Shared connection pool (single connection + threading lock) ───────────────

_db_conn: sqlite3.Connection | None = None
_db_lock = threading.Lock()


def _open_shared_conn() -> sqlite3.Connection:
    conn = water_model.get_connection(water_model.DB_PATH)
    return conn


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield the shared WAL-mode connection under a threading lock.

    WAL allows concurrent readers, but our writes (compute_and_store) delete
    and re-insert across multiple tables, so we serialise all callers with a
    lock to prevent interleaved partial state.
    """
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            _db_conn = _open_shared_conn()
        yield _db_conn


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup: open the shared connection, run migrations, seed empty tables.
    User data in editable tables is never dropped.
    """
    global _db_conn
    _db_conn = _open_shared_conn()
    with _db_lock:
        water_model.init_db(_db_conn)
    yield
    # Shutdown: close shared connection
    with _db_lock:
        if _db_conn is not None:
            _db_conn.close()
            _db_conn = None


app = FastAPI(title="Water Intelligence Engine v2 API", lifespan=lifespan)

# Mount static files for versioned HTML
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "v0" / "0.2.html")


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
app.include_router(recommended_actions_router)


# ── Pydantic models ───────────────────────────────────────────────────────────

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
    fresh_capacity_gal:   float = 100
    grey_capacity_gal:    float = 80
    black_capacity_gal:   float = 40
    current_fresh_gal:    float = 100
    current_grey_gal:     float = 0
    current_black_gal:    float = 0
    climate_multiplier:   float = 1.0
    target_autonomy_days: float = 5
    drift:                float = 0.0
    drift_seed:           int | None = None
    alert_threshold:      float = 0.10
    greywater_recycle:    int = 0

    @field_validator(
        "fresh_capacity_gal", "grey_capacity_gal", "black_capacity_gal",
        "current_fresh_gal", "current_grey_gal", "current_black_gal",
        "target_autonomy_days", "alert_threshold",
        mode="before",
    )
    @classmethod
    def must_be_non_negative(cls, v):
        if v is not None and float(v) < 0:
            raise ValueError("value must be >= 0")
        return v

    @field_validator("climate_multiplier", mode="before")
    @classmethod
    def climate_must_be_positive(cls, v):
        if v is not None and float(v) <= 0:
            raise ValueError("climate_multiplier must be > 0")
        return v

    @field_validator("drift", mode="before")
    @classmethod
    def drift_in_range(cls, v):
        v = float(v)
        if not (0.0 <= v <= 1.0):
            raise ValueError("drift must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def current_within_capacity(self):
        pairs = [
            ("current_fresh_gal", "fresh_capacity_gal"),
            ("current_grey_gal",  "grey_capacity_gal"),
            ("current_black_gal", "black_capacity_gal"),
        ]
        for current_field, cap_field in pairs:
            current = getattr(self, current_field)
            cap     = getattr(self, cap_field)
            if current > cap:
                raise ValueError(
                    f"{current_field} ({current}) cannot exceed "
                    f"{cap_field} ({cap})"
                )
        return self


class BehaviorMultiplierUpdate(BaseModel):
    user_type:   str
    shower_mult: float
    sink_mult:   float
    toilet_mult: float


class ActivityUpdate(BaseModel):
    id:                        int
    name:                      str
    flow_gal_per_min:          float | None
    duration_min:              float | None
    events_per_day_per_person: float | None
    gal_per_unit:              float | None
    grey_pct:                  float
    black_pct:                 float


class InputsUpdate(BaseModel):
    user_types:           list[UserTypeUpdate] | None = None
    tank_environment:     TankEnvironmentUpdate | None = None
    behavior_multipliers: list[BehaviorMultiplierUpdate] | None = None
    activities:           list[ActivityUpdate] | None = None


# ── Daily Usage Heatmap helpers ───────────────────────────────────────────────

HEATMAP_GROUPS = [
    {"name": "Hygiene",    "icon": "🚿", "members": ["Shower", "Bathroom Sink"]},
    {"name": "Kitchen",    "icon": "🍳", "members": ["Kitchen Sink"]},
    {"name": "Sanitation", "icon": "🚽", "members": ["Toilet"]},
    {"name": "Drinking",   "icon": "💧", "members": ["Drinking (Adults)", "Drinking (Children)"]},
]


def _heatmap_ranges(daily_usage_by_day: list, target_days: int) -> dict:
    """Min/max per stream (fresh, grey, black) across all activities × days."""
    if not daily_usage_by_day or target_days <= 0:
        return {
            "fresh": {"min": 0, "max": 1},
            "grey":  {"min": 0, "max": 1},
            "black": {"min": 0, "max": 1},   # was "back" — fixed
        }
    days    = range(1, int(target_days) + 1)
    streams = ("fresh", "grey", "black")      # was ("fresh", "grey", "back") — fixed
    out     = {s: {"min": float("inf"), "max": float("-inf")} for s in streams}
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


def _pivot_daily_usage(raw_rows: list, activity_order: dict) -> list:
    """
    Pivot daily_usage_by_day rows into one dict per activity with
    fresh_{d}, grey_{d}, black_{d}, factor_{d} keys.

    Key 'black' (not 'back') is used consistently.
    """
    by_activity: dict = {}
    for r in raw_rows:
        name   = r["activity_name"]
        day    = r["day_num"]
        fresh  = r["fresh_gal"]
        grey   = r["grey_gal"]
        black  = r["black_gal"]
        factor = r["drift_factor"]
        if name not in by_activity:
            by_activity[name] = {"activity": name}
        by_activity[name][f"fresh_{day}"]  = round(fresh, 2)
        by_activity[name][f"grey_{day}"]   = round(grey, 2)
        by_activity[name][f"black_{day}"]  = round(black, 2)  # was "back" — fixed
        by_activity[name][f"factor_{day}"] = round(factor, 3)
    return sorted(by_activity.values(), key=lambda x: activity_order.get(x["activity"], 999))


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/inputs")
def get_inputs():
    with get_conn() as conn:
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
            "user_types":           user_types,
            "tank_environment":     tank_environment,
            "behavior_multipliers": behavior_multipliers,
            "activities":           activities,
        }


@app.put("/api/inputs")
def put_inputs(payload: InputsUpdate):
    """
    Save user edits then trigger a recompute.
    Validation errors from TankEnvironmentUpdate are raised before any DB write.
    """
    with get_conn() as conn:
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
                t.current_fresh_gal,  t.current_grey_gal,  t.current_black_gal,
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

        # Recompute immediately after saving so GET /api/results is up to date
        water_model.compute_and_store(conn)

    return {"ok": True}


@app.post("/api/compute")
def compute():
    """Explicit recompute trigger (e.g. after external DB edits or forced refresh)."""
    with get_conn() as conn:
        water_model.compute_and_store(conn)
    return {"ok": True}


@app.get("/api/results")
def get_results():
    """
    Pure read of pre-computed results.
    compute_and_store() is no longer called here — results are always
    up to date because PUT /api/inputs triggers it on every save.
    """
    with get_conn() as conn:
        cur = conn.cursor()

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
        if stability_score and "status" not in stability_score and stability_score.get("rating") is not None:
            stability_score["status"] = stability_score["rating"]

        cur.execute("""
            SELECT target_autonomy_days, drift, drift_seed, greywater_recycle
            FROM tank_environment LIMIT 1
        """)
        row_te = cur.fetchone()
        target_days       = int(row_te[0])   if row_te else 5
        drift_val         = float(row_te[1]) if row_te else 0.0
        seed_val          = row_te[2]        if row_te else None
        greywater_recycle = bool(row_te[3])  if row_te else False

        cur.execute("""
            SELECT activity_name, day_num, fresh_gal, grey_gal, black_gal, drift_factor
            FROM daily_usage_by_day ORDER BY activity_name, day_num
        """)
        raw_rows = [dict(r) for r in cur.fetchall()]
        activity_order    = {r["activity_name"]: i for i, r in enumerate(activity_results)}
        daily_usage_by_day = _pivot_daily_usage(raw_rows, activity_order)

        heat_ranges = _heatmap_ranges(daily_usage_by_day, target_days)
        heat_groups = _heatmap_groups(daily_usage_by_day)

        limiting_days  = stability_score.get("limiting_days") if stability_score else None
        stay_supported = limiting_days is not None and limiting_days >= target_days
        recommended_actions = build_recommended_actions(
            stability_score=stability_score,
            tank_projections=tank_projections,
            activity_results=activity_results,
            target_days=target_days,
            greywater_recycle=greywater_recycle,
        )

        return {
            "activity_results":    activity_results,
            "daily_usage_by_day":  daily_usage_by_day,
            "target_days":         target_days,
            "drift":               drift_val,
            "drift_seed":          seed_val,
            "greywater_recycle":   greywater_recycle,
            "tank_projections":    tank_projections,
            "stability_score":     stability_score,
            "heat_ranges":         heat_ranges,
            "heat_groups":         heat_groups,
            "stay_supported":      stay_supported,
            "recommended_actions": recommended_actions,
        }


# ── Realtime: per-day stats and baseline alerts ───────────────────────────────

def _realtime_baseline(activity_results: list) -> dict:
    """Baseline daily totals from activity_result (deterministic)."""
    fresh = sum(r.get("daily_fresh_gal") or 0 for r in activity_results)
    grey  = sum(r.get("grey_added_gal")  or 0 for r in activity_results)
    black = sum(r.get("black_added_gal") or 0 for r in activity_results)
    return {"fresh_gal": round(fresh, 2), "grey_gal": round(grey, 2), "black_gal": round(black, 2)}


def _realtime_toilet_eff_fresh(activity_results: list) -> float:
    for r in activity_results:
        if r.get("activity_name") == "Toilet":
            return float(r.get("daily_fresh_gal") or 0)
    return 0.0


def _realtime_toilet_gross_fresh_for_day(raw_rows: list, day_num: int) -> float:
    for r in raw_rows:
        if r["activity_name"] == "Toilet" and r["day_num"] == day_num:
            return float(r["fresh_gal"])
    return 0.0


def _realtime_gross_fresh_baseline(baseline: dict, toilet_eff: float, toilet_gross_day: float) -> float:
    """Match summed daily_usage fresh: activity_result uses net toilet fresh when greywater recycles."""
    return round(float(baseline["fresh_gal"]) + max(0.0, toilet_gross_day - toilet_eff), 2)


def _realtime_day_totals(raw_rows: list, day_num: int) -> dict:
    """Sum fresh/grey/black for a given day from daily_usage_by_day rows."""
    fresh = sum(r["fresh_gal"] for r in raw_rows if r["day_num"] == day_num)
    grey  = sum(r["grey_gal"]  for r in raw_rows if r["day_num"] == day_num)
    black = sum(r["black_gal"] for r in raw_rows if r["day_num"] == day_num)
    return {"fresh_gal": round(fresh, 2), "grey_gal": round(grey, 2), "black_gal": round(black, 2)}


def _realtime_day_activities(raw_rows: list, day_num: int) -> list:
    """Per-activity usage for a given day."""
    return [
        {
            "activity_name": r["activity_name"],
            "fresh_gal":     round(r["fresh_gal"], 2),
            "grey_gal":      round(r["grey_gal"],  2),
            "black_gal":     round(r["black_gal"], 2),
            "drift_factor":  round(r["drift_factor"], 3),
        }
        for r in raw_rows
        if r["day_num"] == day_num
    ]


@app.get("/api/realtime")
def get_realtime():
    """
    Pure read: per-day stats, cumulative tank levels, and alerts.
    compute_and_store() is no longer called here.
    """
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT target_autonomy_days, fresh_capacity_gal, grey_capacity_gal, black_capacity_gal,
                   current_fresh_gal, current_grey_gal, current_black_gal, alert_threshold,
                   greywater_recycle
            FROM tank_environment LIMIT 1
        """)
        row = cur.fetchone()
        target_days          = max(1, int(row[0])) if row else 5
        fresh_cap            = float(row[1])        if row else 100
        grey_cap             = float(row[2])        if row else 80
        black_cap            = float(row[3])        if row else 40
        cur_fresh            = float(row[4])        if row else 100
        cur_grey             = float(row[5])        if row else 0
        cur_black            = float(row[6])        if row else 0
        alert_threshold_frac = float(row[7])        if row and row[7] is not None else 0.10
        greywater_recycle    = bool(row[8])         if row else False

        tank_capacities = {
            "fresh_gal": round(fresh_cap, 2),
            "grey_gal":  round(grey_cap,  2),
            "black_gal": round(black_cap, 2),
        }

        cur.execute("""
            SELECT activity_name, daily_fresh_gal, grey_added_gal, black_added_gal
            FROM activity_result
        """)
        activity_results = [dict(r) for r in cur.fetchall()]
        baseline         = _realtime_baseline(activity_results)

        cur.execute("""
            SELECT activity_name, day_num, fresh_gal, grey_gal, black_gal, drift_factor
            FROM daily_usage_by_day ORDER BY activity_name, day_num
        """)
        raw_rows         = [dict(r) for r in cur.fetchall()]
        toilet_eff_fresh = _realtime_toilet_eff_fresh(activity_results)

        activity_order     = {r["activity_name"]: i for i, r in enumerate(activity_results)}
        daily_usage_by_day = _pivot_daily_usage(raw_rows, activity_order)  # uses "black" key

        heat_ranges = _heatmap_ranges(daily_usage_by_day, target_days)
        heat_groups = _heatmap_groups(daily_usage_by_day)

        def _cap_fresh(gal): return round(max(0, min(fresh_cap, gal)), 2)
        def _cap_grey(gal):  return round(max(0, min(grey_cap,  gal)), 2)
        def _cap_black(gal): return round(max(0, min(black_cap, gal)), 2)

        running_fresh = cur_fresh
        running_grey  = cur_grey
        running_black = cur_black

        toilet_fresh_by_day = {
            r["day_num"]: r["fresh_gal"]
            for r in raw_rows if r["activity_name"] == "Toilet"
        }

        threshold        = 1.0 + alert_threshold_frac
        days             = []
        prev_day_grey_total = 0.0

        for day_num in range(1, target_days + 1):
            totals     = _realtime_day_totals(raw_rows, day_num)
            activities = _realtime_day_activities(raw_rows, day_num)

            grey_recycled = 0.0
            if greywater_recycle and day_num > 1:
                toilet_fresh_today = toilet_fresh_by_day.get(day_num, 0.0)
                grey_recycled = min(toilet_fresh_today, prev_day_grey_total)

            running_fresh = _cap_fresh(running_fresh - totals["fresh_gal"] + grey_recycled)
            running_grey  = _cap_grey(running_grey   + totals["grey_gal"]  - grey_recycled)
            running_black = _cap_black(running_black  + totals["black_gal"])
            prev_day_grey_total = totals["grey_gal"]

            tank_levels = {
                "fresh_gal": running_fresh,
                "grey_gal":  running_grey,
                "black_gal": running_black,
            }

            toilet_gross_day      = _realtime_toilet_gross_fresh_for_day(raw_rows, day_num)
            baseline_fresh_gross  = _realtime_gross_fresh_baseline(baseline, toilet_eff_fresh, toilet_gross_day)
            alert_fresh = baseline_fresh_gross > 0 and totals["fresh_gal"] > baseline_fresh_gross * threshold
            alert_grey  = baseline["grey_gal"]  > 0 and totals["grey_gal"]  > baseline["grey_gal"]  * threshold
            alert_black = baseline["black_gal"] > 0 and totals["black_gal"] > baseline["black_gal"] * threshold
            alert       = alert_fresh or alert_grey or alert_black

            def _pct_above(baseline_gal, actual_gal):
                if baseline_gal <= 0:
                    return 0
                return round((actual_gal / baseline_gal - 1) * 100)

            alerts_list = []
            if alert_fresh:
                pct = _pct_above(baseline_fresh_gross, totals["fresh_gal"])
                alerts_list.append({"stream": "fresh", "message": f"Fresh water usage is {pct}% more than usual"})
            if alert_grey:
                pct = _pct_above(baseline["grey_gal"], totals["grey_gal"])
                alerts_list.append({"stream": "grey",  "message": f"Grey water usage is {pct}% more than usual"})
            if alert_black:
                pct = _pct_above(baseline["black_gal"], totals["black_gal"])
                alerts_list.append({"stream": "black", "message": f"Black water usage is {pct}% more than usual"})

            days.append({
                "day_num":           int(day_num),
                "stats":             totals,
                "baseline":          baseline,
                "activities":        activities,
                "tank_levels":       tank_levels,
                "alert":             alert,
                "alert_fresh":       alert_fresh,
                "alert_grey":        alert_grey,
                "alert_black":       alert_black,
                "alerts":            alerts_list,
                "grey_recycled_gal": round(grey_recycled, 2),
            })

    return {
        "target_days":         target_days,
        "baseline":            baseline,
        "tank_capacities":     tank_capacities,
        "days":                days,
        "daily_usage_by_day":  daily_usage_by_day,
        "heat_ranges":         heat_ranges,
        "heat_groups":         heat_groups,
        "greywater_recycle":   greywater_recycle,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="localhost", port=8000, reload=True)