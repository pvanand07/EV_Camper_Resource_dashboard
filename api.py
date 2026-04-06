"""
FastAPI backend for Water Intelligence Engine v2.
Exposes editable inputs and computed results.
"""

import math
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

import water_model


@contextmanager
def get_conn():
    conn = sqlite3.connect(water_model.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Single-process: reset DB once per server start. (Multiple uvicorn workers would each reset.)
    with get_conn() as conn:
        water_model.reset_database(conn)
    yield


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


def _projection_available_gallons(projection: dict) -> float:
    if not projection:
        return 0.0
    if projection["tank"] == "Fresh":
        return max(0.0, float(projection.get("current_gal") or 0.0))
    return max(0.0, float(projection.get("capacity_gal") or 0.0) - float(projection.get("current_gal") or 0.0))


def _projection_daily_load(projection: dict) -> float:
    if not projection:
        return 0.0
    delta = float(projection.get("daily_delta_gal") or 0.0)
    return abs(delta) if projection["tank"] == "Fresh" else max(0.0, delta)


def _days_from_projection(projection: dict, daily_load: float | None = None) -> float:
    if not projection:
        return 0.0
    load = _projection_daily_load(projection) if daily_load is None else float(daily_load)
    if load <= 0:
        return math.inf
    return _projection_available_gallons(projection) / load


def _activity_stream_key(tank: str) -> str:
    return {
        "Fresh": "daily_fresh_gal",
        "Grey": "grey_added_gal",
        "Black": "black_added_gal",
    }[tank]


def _service_day(days_available: float, target_days: int) -> int:
    if target_days <= 0:
        return 1
    return max(1, min(int(target_days), int(math.floor(max(0.0, days_available))) + 1))


def _activity_action_copy(activity_name: str, tank: str) -> tuple[str, str]:
    by_tank = {
        "Fresh": {
            "Shower": (
                "Reduce shower duration or shower frequency",
                "Showers are the biggest fresh-water driver right now.",
            ),
            "Kitchen Sink": (
                "Reduce kitchen sink water use",
                "Kitchen sink use is the biggest fresh-water driver right now.",
            ),
            "Bathroom Sink": (
                "Reduce bathroom sink water use",
                "Bathroom sink use is one of the main fresh-water drivers right now.",
            ),
            "Toilet": (
                "Reduce toilet fresh-water demand",
                "Lower flush volume where practical, especially if grey water reuse is unavailable.",
            ),
            "Drinking (Adults)": (
                "Reduce adult drinking water drawn from the tank",
                "Bring separate drinking water or refill bottles off-board where possible.",
            ),
            "Drinking (Children)": (
                "Reduce children's drinking water drawn from the tank",
                "Bring separate drinking water or refill bottles off-board where possible.",
            ),
        },
        "Grey": {
            "Shower": (
                "Reduce shower duration or shower frequency",
                "Showers are the biggest grey-tank contributor right now.",
            ),
            "Kitchen Sink": (
                "Reduce kitchen sink water use",
                "Kitchen sink use is the biggest grey-tank contributor right now.",
            ),
            "Bathroom Sink": (
                "Reduce bathroom sink water use",
                "Bathroom sink use is one of the main grey-tank contributors right now.",
            ),
        },
        "Black": {
            "Toilet": (
                "Reduce toilet usage where possible",
                "Use external facilities when available or reduce flush frequency where practical.",
            ),
        },
    }
    canned = by_tank.get(tank, {})
    if activity_name in canned:
        return canned[activity_name]
    return (
        f"Reduce {activity_name.lower()} demand",
        f"Lower {activity_name.lower()} usage to reduce {tank.lower()} load during the stay.",
    )


def _build_recommended_actions(
    stability_score: dict | None,
    tank_projections: list[dict],
    activity_results: list[dict],
    target_days: int,
    greywater_recycle: bool,
) -> list[dict]:
    if not stability_score:
        return []

    limiting_tank = stability_score.get("limiting_tank")
    limiting_days = float(stability_score.get("limiting_days") or 0.0)
    if not limiting_tank or limiting_days >= target_days:
        return []

    projection_by_tank = {row["tank"]: row for row in tank_projections}
    limiting_projection = projection_by_tank.get(limiting_tank)
    if not limiting_projection:
        return []

    limiting_load = _projection_daily_load(limiting_projection)
    available_gallons = _projection_available_gallons(limiting_projection)
    if limiting_load <= 0 or target_days <= 0:
        return []

    gap_days = max(0.0, target_days - limiting_days)
    required_daily_reduction = max(0.0, limiting_load - (available_gallons / target_days))
    required_reduction_pct = (required_daily_reduction / limiting_load * 100.0) if limiting_load > 0 else 0.0
    extra_capacity_needed = max(0.0, target_days * limiting_load - available_gallons)
    actions: list[dict] = []

    def add_action(
        category: str,
        title: str,
        summary: str,
        estimated_days_gain: float,
        estimated_daily_change_gal: float = 0.0,
        tank: str | None = None,
        activity_name: str | None = None,
    ) -> None:
        actions.append({
            "priority": len(actions) + 1,
            "category": category,
            "tank": tank or limiting_tank,
            "activity_name": activity_name,
            "title": title,
            "summary": summary,
            "estimated_days_gain": round(max(0.0, estimated_days_gain), 2),
            "estimated_daily_change_gal": round(max(0.0, estimated_daily_change_gal), 2),
        })

    add_action(
        category="gap_summary",
        title=f"Close the {limiting_tank.lower()} gap",
        summary=(
            f"{gap_days:.2f} d short — cut {required_daily_reduction:.1f} gal/day "
            f"({required_reduction_pct:.0f}%) or add {extra_capacity_needed:.0f} gal of {limiting_tank.lower()} capacity."
        ),
        estimated_days_gain=gap_days,
        estimated_daily_change_gal=required_daily_reduction,
    )

    fresh_projection = projection_by_tank.get("Fresh")
    grey_projection = projection_by_tank.get("Grey")
    black_projection = projection_by_tank.get("Black")
    total_fresh = sum(float(r.get("daily_fresh_gal") or 0.0) for r in activity_results)
    total_grey = sum(float(r.get("grey_added_gal") or 0.0) for r in activity_results)
    total_black = sum(float(r.get("black_added_gal") or 0.0) for r in activity_results)
    toilet_fresh = next(
        (float(r.get("daily_fresh_gal") or 0.0) for r in activity_results if r.get("activity_name") == "Toilet"),
        0.0,
    )

    if limiting_tank == "Fresh":
        extra_start_gallons = max(
            0.0,
            float(limiting_projection.get("capacity_gal") or 0.0) - float(limiting_projection.get("current_gal") or 0.0),
        )
        if extra_start_gallons > 0:
            gain_days = extra_start_gallons / limiting_load
            add_action(
                category="starting_state",
                tank="Fresh",
                title="Top up the fresh tank before departure",
                summary=(
                    f"Tank is {extra_start_gallons:.0f} gal below capacity — topping up before leaving adds {gain_days:.2f} days."
                ),
                estimated_days_gain=gain_days,
            )

        refill_day = _service_day(limiting_days, target_days)
        refill_amount = min(
            float(limiting_projection.get("capacity_gal") or 0.0),
            max(extra_capacity_needed, required_daily_reduction),
        )
        refill_gain = float(limiting_projection.get("capacity_gal") or 0.0) / limiting_load
        add_action(
            category="service_stop",
            tank="Fresh",
            title=f"Must refill fresh water on day {refill_day} of your trip",
            summary=(
                    f"Runs out day {limiting_days:.1f} — refill by day {refill_day}. "
                    f"Add {refill_amount:.0f} gal to cover the gap; full tank extends by {refill_gain:.1f} days."
                ),
            estimated_days_gain=refill_gain,
        )
    else:
        reclaimable_gallons = max(0.0, float(limiting_projection.get("current_gal") or 0.0))
        if reclaimable_gallons > 0:
            gain_days = reclaimable_gallons / limiting_load
            add_action(
                category="starting_state",
                tank=limiting_tank,
                title=f"Empty the {limiting_tank.lower()} tank before departure",
                summary=(
                    f"{reclaimable_gallons:.0f} gal already in the {limiting_tank.lower()} tank — dump before leaving to gain {gain_days:.2f} days."
                ),
                estimated_days_gain=gain_days,
            )

    # Waste tanks: recommend service whenever autonomy falls short of the target stay,
    # not only when that tank is the single limiting constraint (e.g. fresh may fail first).
    grey_days_val = float(stability_score.get("grey_days") or 0.0)
    if grey_projection and grey_days_val < target_days:
        g_load = _projection_daily_load(grey_projection)
        if g_load > 0:
            grey_service_day = _service_day(grey_days_val, target_days)
            grey_cap = float(grey_projection.get("capacity_gal") or 0.0)
            grey_service_gain = grey_cap / g_load
            add_action(
                category="service_stop",
                tank="Grey",
                title="Plan one grey tank service during the stay",
                summary=(
                    f"Fills by day {grey_days_val:.1f} — dump by day {grey_service_day} to stay ahead. "
                    f"Full service ({grey_cap:.0f} gal) adds {grey_service_gain:.1f} days."
                ),
                estimated_days_gain=grey_service_gain,
            )

    black_days_val = float(stability_score.get("black_days") or 0.0)
    if black_projection and black_days_val < target_days:
        b_load = _projection_daily_load(black_projection)
        if b_load > 0:
            black_service_day = _service_day(black_days_val, target_days)
            black_cap = float(black_projection.get("capacity_gal") or 0.0)
            black_service_gain = black_cap / b_load
            add_action(
                category="service_stop",
                tank="Black",
                title=f"Plan one black tank service on day {black_service_day}",
                summary=(
                    f"Fills by day {black_days_val:.1f} — dump on day {black_service_day}. "
                    f"Full service ({black_cap:.0f} gal) adds {black_service_gain:.1f} days."
                ),
                estimated_days_gain=black_service_gain,
            )

    if not greywater_recycle and fresh_projection and grey_projection:
        recycled_gallons = min(toilet_fresh, total_grey)
        if recycled_gallons > 0:
            fresh_days = _days_from_projection(fresh_projection, total_fresh - recycled_gallons)
            grey_days = _days_from_projection(grey_projection, total_grey - recycled_gallons)
            black_days = _days_from_projection(black_projection, total_black) if black_projection else math.inf
            new_limiting_days = min(fresh_days, grey_days, black_days)
            gain_days = new_limiting_days - limiting_days
            if gain_days > 0.05:
                add_action(
                    category="feature_toggle",
                    title="Turn on grey water reuse for toilet flushing",
                    summary=(
                        f"Redirect {recycled_gallons:.1f} gal/day of grey to toilet flushing — gains {gain_days:.2f} days overall."
                    ),
                    estimated_days_gain=gain_days,
                    estimated_daily_change_gal=recycled_gallons,
                )

    stream_key = _activity_stream_key(limiting_tank)
    contributors = sorted(
        (
            {
                "activity_name": row["activity_name"],
                "stream_load": float(row.get(stream_key) or 0.0),
                "stream_share_pct": (float(row.get(stream_key) or 0.0) / limiting_load * 100.0) if limiting_load > 0 else 0.0,
            }
            for row in activity_results
            if float(row.get(stream_key) or 0.0) > 0
        ),
        key=lambda row: row["stream_load"],
        reverse=True,
    )

    for contributor in contributors[:2]:
        stream_load = contributor["stream_load"]
        if stream_load <= 0:
            continue
        cut_pct = min(60, max(15, int(math.ceil((required_daily_reduction / stream_load) * 100 / 5.0) * 5)))
        saved_gallons = stream_load * (cut_pct / 100.0)
        improved_days = _days_from_projection(limiting_projection, max(0.0, limiting_load - saved_gallons))
        gain_days = improved_days - limiting_days
        if gain_days <= 0.05:
            continue
        title, hint = _activity_action_copy(contributor["activity_name"], limiting_tank)
        add_action(
            category="activity_reduction",
            tank=limiting_tank,
            activity_name=contributor["activity_name"],
            title=title,
            summary=(
                f"{contributor['activity_name']} is {contributor['stream_share_pct']:.0f}% of the load. "
                f"Cut {cut_pct}% → −{saved_gallons:.1f} gal/day, +{gain_days:.2f} days."
            ),
            estimated_days_gain=gain_days,
            estimated_daily_change_gal=saved_gallons,
        )

    return actions


# ─── API Endpoints ───────────────────────────────────────────────────────────

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
            "user_types": user_types,
            "tank_environment": tank_environment,
            "behavior_multipliers": behavior_multipliers,
            "activities": activities,
        }


@app.put("/api/inputs")
def put_inputs(payload: InputsUpdate):
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
        water_model.compute_and_store(conn)
    return {"ok": True}


@app.get("/api/results")
def get_results():
    with get_conn() as conn:
        water_model.compute_and_store(conn)
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

        # Calculate stay_supported based on projected limiting days vs target
        limiting_days = stability_score.get("limiting_days") if stability_score else None
        stay_supported = limiting_days is not None and limiting_days >= target_days
        recommended_actions = _build_recommended_actions(
            stability_score=stability_score,
            tank_projections=tank_projections,
            activity_results=activity_results,
            target_days=target_days,
            greywater_recycle=greywater_recycle,
        )

        return {
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
            "stay_supported": stay_supported,
            "recommended_actions": recommended_actions,
        }


# ─── Realtime: per-day stats and 10% baseline alerts ─────────────────────────

def _realtime_baseline(activity_results: list) -> dict:
    """Baseline daily totals from activity_result (deterministic)."""
    fresh = sum(r.get("daily_fresh_gal") or 0 for r in activity_results)
    grey = sum(r.get("grey_added_gal") or 0 for r in activity_results)
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
        toilet_eff_fresh = _realtime_toilet_eff_fresh(activity_results)

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

            toilet_gross_day = _realtime_toilet_gross_fresh_for_day(raw_rows, day_num)
            baseline_fresh_gross = _realtime_gross_fresh_baseline(
                baseline, toilet_eff_fresh, toilet_gross_day
            )
            alert_fresh = baseline_fresh_gross > 0 and totals["fresh_gal"] > baseline_fresh_gross * threshold
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
                pct = _pct_above(baseline_fresh_gross, totals["fresh_gal"])
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
    uvicorn.run("api:app", host="localhost", port=8000, reload=True)