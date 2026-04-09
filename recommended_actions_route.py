"""
Recommended actions route for Water Intelligence Engine v2.

Changes from original:
- Removed the local get_conn() / sqlite3.connect() — now imports and uses
  the shared WAL-mode connection from api.py via get_conn().
- GET /api/recommended-actions is a pure read; compute_and_store() is no
  longer called here (it runs on PUT /api/inputs and POST /api/compute).
- build_recommended_actions() is unchanged in logic and signature.
"""

import math
from fastapi import APIRouter

import water_model

# Import the shared connection manager from api so this route uses the same
# WAL-mode connection and threading lock as every other endpoint.
# api.py imports this module, so we use a lazy import inside the route handler
# to avoid a circular import at module load time.

router = APIRouter(prefix="/api")


# ── Pure computation helpers (no DB access) ───────────────────────────────────

def _projection_available_gallons(projection: dict) -> float:
    if not projection:
        return 0.0
    if projection["tank"] == "Fresh":
        return max(0.0, float(projection.get("current_gal") or 0.0))
    return max(
        0.0,
        float(projection.get("capacity_gal") or 0.0) - float(projection.get("current_gal") or 0.0),
    )


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
        "Grey":  "grey_added_gal",
        "Black": "black_added_gal",
    }[tank]


def _service_day(days_available: float, target_days: int) -> int:
    if target_days <= 0:
        return 1
    return max(1, min(int(target_days), int(math.floor(max(0.0, days_available))) + 1))


def _tank_label(tank: str) -> str:
    return "grey water tank" if tank == "Grey" else f"{tank.lower()} tank"


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
                "Showers are the biggest grey water tank contributor right now.",
            ),
            "Kitchen Sink": (
                "Reduce kitchen sink water use",
                "Kitchen sink use is the biggest grey water tank contributor right now.",
            ),
            "Bathroom Sink": (
                "Reduce bathroom sink water use",
                "Bathroom sink use is one of the main grey water tank contributors right now.",
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


# ── Core recommendation engine (pure function, no DB access) ─────────────────

def build_recommended_actions(
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

    projection_by_tank  = {row["tank"]: row for row in tank_projections}
    limiting_projection = projection_by_tank.get(limiting_tank)
    if not limiting_projection:
        return []

    limiting_load     = _projection_daily_load(limiting_projection)
    limiting_tank_label = _tank_label(limiting_tank)
    available_gallons = _projection_available_gallons(limiting_projection)
    if limiting_load <= 0 or target_days <= 0:
        return []

    gap_days                  = max(0.0, target_days - limiting_days)
    required_daily_reduction  = max(0.0, limiting_load - (available_gallons / target_days))
    required_reduction_pct    = (required_daily_reduction / limiting_load * 100.0) if limiting_load > 0 else 0.0
    extra_capacity_needed     = max(0.0, target_days * limiting_load - available_gallons)
    actions: list[dict]       = []

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
            "priority":                   len(actions) + 1,
            "category":                   category,
            "tank":                       tank or limiting_tank,
            "activity_name":              activity_name,
            "title":                      title,
            "summary":                    summary,
            "estimated_days_gain":        round(max(0.0, estimated_days_gain), 2),
            "estimated_daily_change_gal": round(max(0.0, estimated_daily_change_gal), 2),
        })

    # ── Gap summary
    add_action(
        category="gap_summary",
        title=f"Close the {limiting_tank_label} gap",
        summary=(
            f"{gap_days:.2f} d short - cut {required_daily_reduction:.1f} gal/day "
            f"({required_reduction_pct:.0f}%) or add {extra_capacity_needed:.0f} gal "
            f"of {limiting_tank_label} capacity."
        ),
        estimated_days_gain=gap_days,
        estimated_daily_change_gal=required_daily_reduction,
    )

    fresh_projection = projection_by_tank.get("Fresh")
    grey_projection  = projection_by_tank.get("Grey")
    black_projection = projection_by_tank.get("Black")
    total_fresh      = sum(float(r.get("daily_fresh_gal") or 0.0) for r in activity_results)
    total_grey       = sum(float(r.get("grey_added_gal")  or 0.0) for r in activity_results)
    total_black      = sum(float(r.get("black_added_gal") or 0.0) for r in activity_results)
    toilet_fresh     = next(
        (float(r.get("daily_fresh_gal") or 0.0) for r in activity_results if r.get("activity_name") == "Toilet"),
        0.0,
    )

    # ── Starting-state actions
    if limiting_tank == "Fresh":
        extra_start_gallons = max(
            0.0,
            float(limiting_projection.get("capacity_gal") or 0.0)
            - float(limiting_projection.get("current_gal") or 0.0),
        )
        if extra_start_gallons > 0:
            gain_days = extra_start_gallons / limiting_load
            add_action(
                category="starting_state",
                tank="Fresh",
                title="Top up the fresh tank before departure",
                summary=(
                    f"Tank is {extra_start_gallons:.0f} gal below capacity - "
                    f"topping up before leaving adds {gain_days:.2f} days."
                ),
                estimated_days_gain=gain_days,
            )

        refill_day    = _service_day(limiting_days, target_days)
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
                f"Runs out day {limiting_days:.1f} - refill by day {refill_day}. "
                f"Add {refill_amount:.0f} gal to cover the gap; "
                f"full tank extends by {refill_gain:.1f} days."
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
                title=f"Empty the {limiting_tank_label} before departure",
                summary=(
                    f"{reclaimable_gallons:.0f} gal already in the {limiting_tank_label} - "
                    f"dump before leaving to gain {gain_days:.2f} days."
                ),
                estimated_days_gain=gain_days,
            )

    # ── Service-stop actions for grey / black when not the limiting tank
    grey_days_val = float(stability_score.get("grey_days") or 0.0)
    if grey_projection and grey_days_val < target_days:
        g_load = _projection_daily_load(grey_projection)
        if g_load > 0:
            grey_service_day  = _service_day(grey_days_val, target_days)
            grey_cap          = float(grey_projection.get("capacity_gal") or 0.0)
            grey_service_gain = grey_cap / g_load
            add_action(
                category="service_stop",
                tank="Grey",
                title="Plan one grey water tank service during the stay",
                summary=(
                    f"Fills by day {grey_days_val:.1f} - dump by day {grey_service_day} to stay ahead. "
                    f"Full service ({grey_cap:.0f} gal) adds {grey_service_gain:.1f} days."
                ),
                estimated_days_gain=grey_service_gain,
            )

    black_days_val = float(stability_score.get("black_days") or 0.0)
    if black_projection and black_days_val < target_days:
        b_load = _projection_daily_load(black_projection)
        if b_load > 0:
            black_service_day  = _service_day(black_days_val, target_days)
            black_cap          = float(black_projection.get("capacity_gal") or 0.0)
            black_service_gain = black_cap / b_load
            add_action(
                category="service_stop",
                tank="Black",
                title=f"Plan one black tank service on day {black_service_day}",
                summary=(
                    f"Fills by day {black_days_val:.1f} - dump on day {black_service_day}. "
                    f"Full service ({black_cap:.0f} gal) adds {black_service_gain:.1f} days."
                ),
                estimated_days_gain=black_service_gain,
            )

    # ── Grey-water reuse toggle
    if not greywater_recycle and fresh_projection and grey_projection:
        recycled_gallons = min(toilet_fresh, total_grey)
        if recycled_gallons > 0:
            fresh_days_new = _days_from_projection(fresh_projection, total_fresh - recycled_gallons)
            grey_days_new  = _days_from_projection(grey_projection,  total_grey  - recycled_gallons)
            black_days_new = _days_from_projection(black_projection, total_black) if black_projection else math.inf
            new_limiting_days = min(fresh_days_new, grey_days_new, black_days_new)
            gain_days = new_limiting_days - limiting_days
            if gain_days > 0.05:
                add_action(
                    category="feature_toggle",
                    title="Turn on grey water reuse for toilet flushing",
                    summary=(
                        f"Redirect {recycled_gallons:.1f} gal/day of grey to toilet flushing - "
                        f"gains {gain_days:.2f} days overall."
                    ),
                    estimated_days_gain=gain_days,
                    estimated_daily_change_gal=recycled_gallons,
                )

    # ── Activity-reduction actions for top-2 contributors to limiting stream
    stream_key   = _activity_stream_key(limiting_tank)
    contributors = sorted(
        (
            {
                "activity_name":   row["activity_name"],
                "stream_load":     float(row.get(stream_key) or 0.0),
                "stream_share_pct": (
                    float(row.get(stream_key) or 0.0) / limiting_load * 100.0
                ) if limiting_load > 0 else 0.0,
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
        cut_pct = min(
            60,
            max(15, int(math.ceil((required_daily_reduction / stream_load) * 100 / 5.0) * 5)),
        )
        saved_gallons = stream_load * (cut_pct / 100.0)
        improved_days = _days_from_projection(
            limiting_projection, max(0.0, limiting_load - saved_gallons)
        )
        gain_days = improved_days - limiting_days
        if gain_days <= 0.05:
            continue
        title, _ = _activity_action_copy(contributor["activity_name"], limiting_tank)
        add_action(
            category="activity_reduction",
            tank=limiting_tank,
            activity_name=contributor["activity_name"],
            title=title,
            summary=(
                f"{contributor['activity_name']} is {contributor['stream_share_pct']:.0f}% of the load. "
                f"Cut {cut_pct}% -> -{saved_gallons:.1f} gal/day, +{gain_days:.2f} days."
            ),
            estimated_days_gain=gain_days,
            estimated_daily_change_gal=saved_gallons,
        )

    return actions


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("/recommended-actions")
def get_recommended_actions():
    """
    Pure read of pre-computed results.
    compute_and_store() is no longer called here — results are always
    current because PUT /api/inputs triggers it on every save.
    Uses the shared WAL-mode connection from api.py.
    """
    # Lazy import to avoid circular dependency (api imports this module).
    from api import get_conn

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
        row             = cur.fetchone()
        stability_score = dict(row) if row else None

        cur.execute("SELECT target_autonomy_days, greywater_recycle FROM tank_environment LIMIT 1")
        row_te            = cur.fetchone()
        target_days       = int(row_te[0])  if row_te else 5
        greywater_recycle = bool(row_te[1]) if row_te else False

    recommended_actions = build_recommended_actions(
        stability_score=stability_score,
        tank_projections=tank_projections,
        activity_results=activity_results,
        target_days=target_days,
        greywater_recycle=greywater_recycle,
    )

    limiting_days  = stability_score.get("limiting_days") if stability_score else None
    stay_supported = limiting_days is not None and limiting_days >= target_days

    return {
        "target_days":          target_days,
        "stay_supported":       stay_supported,
        "stability_score":      stability_score,
        "recommended_actions":  recommended_actions,
    }