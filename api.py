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


# ─── Pydantic models ────────────────────────────────────────────────────────

class UserTypeUpdate(BaseModel):
    name: str
    count: int
    is_child: int = 0


class TankEnvironmentUpdate(BaseModel):
    fresh_capacity_gal: float = 100
    grey_capacity_gal: float = 80
    black_capacity_gal: float = 40
    current_fresh_gal: float = 0
    current_grey_gal: float = 0
    current_black_gal: float = 0
    climate_multiplier: float = 1.0
    target_autonomy_days: float = 5


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
            "fresh_capacity_gal": row["fresh_capacity_gal"],
            "grey_capacity_gal": row["grey_capacity_gal"],
            "black_capacity_gal": row["black_capacity_gal"],
            "current_fresh_gal": row["current_fresh_gal"],
            "current_grey_gal": row["current_grey_gal"],
            "current_black_gal": row["current_black_gal"],
            "climate_multiplier": row["climate_multiplier"],
            "target_autonomy_days": row["target_autonomy_days"],
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
                    climate_multiplier = ?, target_autonomy_days = ?
                WHERE id = 1
            """, (
                t.fresh_capacity_gal, t.grey_capacity_gal, t.black_capacity_gal,
                t.current_fresh_gal, t.current_grey_gal, t.current_black_gal,
                t.climate_multiplier, t.target_autonomy_days,
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

        # Daily usage split across target days: Activity | fresh_1 | grey_1 | back_1 | fresh_2 | ...
        cur.execute("SELECT target_autonomy_days FROM tank_environment LIMIT 1")
        row_te = cur.fetchone()
        target_days = int(row_te[0]) if row_te else 5
        cur.execute("""
            SELECT activity_name, day_num, fresh_gal, grey_gal, black_gal
            FROM daily_usage_by_day ORDER BY activity_name, day_num
        """)
        raw = cur.fetchall()
        # Pivot: group by activity, build { activity, fresh_1, grey_1, back_1, fresh_2, ... }
        by_activity = {}
        for r in raw:
            name, day, fresh, grey, black = r
            if name not in by_activity:
                by_activity[name] = {"activity": name}
            by_activity[name][f"fresh_{day}"] = round(fresh, 2)
            by_activity[name][f"grey_{day}"] = round(grey, 2)
            by_activity[name][f"back_{day}"] = round(black, 2)
        # Preserve activity order from activity_results
        order = {r["activity_name"]: i for i, r in enumerate(activity_results)}
        daily_usage_by_day = sorted(by_activity.values(), key=lambda x: order.get(x["activity"], 999))

        return {
            "effective_multipliers": {"shower": eff_shower, "sink": eff_sink, "toilet": eff_toilet},
            "activity_results": activity_results,
            "daily_usage_by_day": daily_usage_by_day,
            "target_days": target_days,
            "tank_projections": tank_projections,
            "stability_score": stability_score,
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)