from flask import Blueprint, request, jsonify, session, current_app
from db import get_db
from subsystems.integration.auth import require_role
import os, time
from werkzeug.utils import secure_filename
import math

collector_bp = Blueprint("collector", __name__)


def _haversine_km(lat1, lng1, lat2, lng2):
    # radius of earth (km)
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


@collector_bp.post("/api/collector/route_optimize")
def route_optimize():
    """Optimize collector route based on residents' saved map coordinates.

    Body JSON: {"start_lat": ..., "start_lng": ...}
    Returns an ordered list of assigned logs.
    """
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    data = request.get_json(silent=True) or {}
    start_lat = data.get("start_lat")
    start_lng = data.get("start_lng")
    try:
        start_lat = float(start_lat) if start_lat is not None and start_lat != "" else None
        start_lng = float(start_lng) if start_lng is not None and start_lng != "" else None
    except (TypeError, ValueError):
        return jsonify(error="Invalid start_lat/start_lng"), 400

    collector_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()
    # Only logs assigned to this collector and still waiting for collection/verification
    cur.execute(
        """
        SELECT rl.log_id, rl.created_at, rl.waste_type, rl.weight,
               u.user_id AS resident_id, u.name AS resident_name,
               COALESCE(u.address,'') AS address,
               u.address_lat, u.address_lng
        FROM recycling_logs rl
        JOIN users u ON u.user_id = rl.user_id
        WHERE rl.status='Assigned' AND rl.assigned_collector_id=?
        ORDER BY rl.log_id DESC
        """,
        (collector_id,),
    )
    items = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Keep only items with coordinates (route optimization needs map points)
    pts = [it for it in items if it.get("address_lat") is not None and it.get("address_lng") is not None]
    missing = [it for it in items if it not in pts]

    if not pts:
        return jsonify(stops=[], total_km=0, missing=missing)

    # Nearest-neighbor heuristic (fast + good enough for demo)
    remaining = pts[:]
    ordered = []

    if start_lat is None or start_lng is None:
        cur_lat = float(remaining[0]["address_lat"])
        cur_lng = float(remaining[0]["address_lng"])
    else:
        cur_lat = float(start_lat)
        cur_lng = float(start_lng)

    total = 0.0
    while remaining:
        best_i = 0
        best_d = None
        for i, it in enumerate(remaining):
            d = _haversine_km(cur_lat, cur_lng, float(it["address_lat"]), float(it["address_lng"]))
            if best_d is None or d < best_d:
                best_d = d
                best_i = i
        nxt = remaining.pop(best_i)
        dist = float(best_d or 0.0)
        total += dist
        nxt_out = dict(nxt)
        nxt_out["distance_from_prev_km"] = round(dist, 3)
        nxt_out["cumulative_km"] = round(total, 3)
        ordered.append(nxt_out)
        cur_lat = float(nxt["address_lat"])
        cur_lng = float(nxt["address_lng"])

    return jsonify(stops=ordered, total_km=round(total, 3), missing=missing)

@collector_bp.get("/api/collector/zones")
def zones():
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT z.zone_id, z.name
        FROM zones z
        JOIN collector_assignments ca ON z.zone_id = ca.zone_id
        WHERE ca.collector_id = ?
        """,
        (session["user_id"],),
    )
    zones = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(zones=zones)

@collector_bp.get("/api/collector/routes")
def routes():
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT route_id, route_date, optimized_path
        FROM routes
        WHERE collector_id=?
        ORDER BY route_date DESC
        LIMIT 1
        """,
        (session["user_id"],),
    )
    routes = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(routes=routes)


@collector_bp.post("/api/collector/route/optimize")
def optimize_route():
    """Optimize a collection route using resident address coordinates.

    Body JSON: {"start_lat": <float>, "start_lng": <float>}
    Returns ordered stops using a simple nearest-neighbor heuristic.
    """
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    data = request.get_json(silent=True) or {}
    try:
        start_lat = float(data.get("start_lat")) if data.get("start_lat") is not None else None
        start_lng = float(data.get("start_lng")) if data.get("start_lng") is not None else None
    except (TypeError, ValueError):
        start_lat, start_lng = None, None

    collector_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rl.log_id, rl.created_at, rl.waste_type, rl.weight,
               u.user_id AS resident_id, u.name AS resident_name,
               COALESCE(u.address,'') AS address,
               u.address_lat, u.address_lng
        FROM recycling_logs rl
        JOIN users u ON u.user_id = rl.user_id
        WHERE rl.status='Assigned'
          AND rl.assigned_collector_id=?
        ORDER BY rl.log_id
        """,
        (collector_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Keep only stops with coordinates
    stops = [r for r in rows if r.get("address_lat") is not None and r.get("address_lng") is not None]
    if not stops:
        return jsonify(stops=[], total_km=0.0)

    if start_lat is None or start_lng is None:
        # fallback: start from the first stop
        start_lat = float(stops[0]["address_lat"])
        start_lng = float(stops[0]["address_lng"])

    remaining = stops[:]
    route = []
    cur_lat, cur_lng = start_lat, start_lng
    total = 0.0

    while remaining:
        # pick nearest next stop
        best_i = 0
        best_d = None
        for i, s in enumerate(remaining):
            d = _haversine_km(cur_lat, cur_lng, float(s["address_lat"]), float(s["address_lng"]))
            if best_d is None or d < best_d:
                best_d = d
                best_i = i
        nxt = remaining.pop(best_i)
        dist = float(best_d or 0.0)
        total += dist
        route.append({
            "log_id": nxt["log_id"],
            "resident_id": nxt["resident_id"],
            "resident_name": nxt["resident_name"],
            "address": nxt["address"],
            "lat": float(nxt["address_lat"]),
            "lng": float(nxt["address_lng"]),
            "distance_from_prev_km": round(dist, 3),
            "waste_type": nxt["waste_type"],
            "weight": nxt["weight"],
            "created_at": nxt["created_at"],
        })
        cur_lat, cur_lng = float(nxt["address_lat"]), float(nxt["address_lng"])

    return jsonify(stops=route, total_km=round(total, 3))

@collector_bp.get("/api/collector/daily_schedule")
def daily_schedule():
    """
    Simple and correct version:
    Collector daily schedule = pickup schedules of their assigned zones.
    """
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT z.name AS zone_name, ps.day, ps.time
        FROM collector_assignments ca
        JOIN zones z ON ca.zone_id = z.zone_id
        JOIN pickup_schedules ps ON ps.zone_id = z.zone_id
        WHERE ca.collector_id=?
        ORDER BY z.zone_id, ps.schedule_id
        """,
        (session["user_id"],),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(schedule=rows)

@collector_bp.post("/api/collector/status")
def update_status():
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    data = request.get_json(force=True)
    zone_raw = (data.get("zone_id") or "").strip()
    status = (data.get("status") or "").strip()

    if not status:
        return jsonify(error="status required"), 400

    zone_id = None
    if zone_raw:
        try:
            zone_id = int(zone_raw)
        except (TypeError, ValueError):
            return jsonify(error="Invalid zone_id"), 400
    else:
        # If collector has at least one assigned zone, use the first one (optional)
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT zone_id FROM collector_assignments WHERE collector_id=? ORDER BY zone_id LIMIT 1", (session["user_id"],))
        r = cur.fetchone()
        conn.close()
        if r:
            zone_id = r["zone_id"]

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO collection_status(collector_id, zone_id, status)
        VALUES (?,?,?)
        """,
        (session["user_id"], zone_id, status),
    )
    conn.commit()
    conn.close()
    return jsonify(ok=True)

@collector_bp.post("/api/collector/issue")
def report_issue():
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    data = request.get_json(force=True)
    zone_id = data.get("zone_id")
    issue_type = (data.get("issue_type") or "").strip()

    if not zone_id or not issue_type:
        return jsonify(error="zone_id and issue_type required"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO bin_issues(collector_id, zone_id, issue_type)
        VALUES (?,?,?)
        """,
        (session["user_id"], zone_id, issue_type),
    )
    conn.commit()
    conn.close()
    return jsonify(ok=True)


# ------------------------------
# Rewards verification workflow
# ------------------------------

@collector_bp.get("/api/collector/rewards/pending")
def pending_reward_requests():
    """Collector views recycling submissions assigned to them by admin that need verification."""
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    collector_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    # Admin assigns collector per log. Collector only sees their assigned logs.
    cur.execute(
        """
        SELECT rl.log_id, rl.created_at, rl.waste_type, rl.weight, rl.image_url,
               rl.status, rl.points_earned,
               u.user_id AS resident_id, u.name AS resident_name, u.phone AS resident_phone,
               u.zone_id, z.name AS zone_name
        FROM recycling_logs rl
        JOIN users u ON u.user_id = rl.user_id
        JOIN zones z ON z.zone_id = u.zone_id
        WHERE rl.status = 'Assigned'
          AND rl.assigned_collector_id = ?
        ORDER BY rl.log_id DESC
        """,
        (collector_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(requests=rows)


@collector_bp.post("/api/collector/rewards/<int:log_id>/verify")
def verify_reward_request(log_id: int):
    """Collector verifies a resident submission.

    Body JSON:
      {"action": "verify"|"reject", "reason": "optional"}
    """
    if not require_role("collector"):
        return jsonify(error="Not logged in as collector."), 401

    # Support both JSON and FormData (FormData allows photo upload proof)
    if request.is_json:
        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "").strip().lower()
        reason = (data.get("reason") or "").strip()
        uploaded = None
    else:
        action = (request.form.get("action") or "").strip().lower()
        reason = (request.form.get("reason") or "").strip()
        uploaded = request.files.get("proof")

    if action not in {"verify", "reject"}:
        return jsonify(error="action must be 'verify' or 'reject'"), 400

    collector_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    # Ensure this log is assigned to the collector
    cur.execute(
        """
        SELECT rl.user_id AS resident_id, rl.status, rl.assigned_collector_id,
               u.zone_id
        FROM recycling_logs rl
        JOIN users u ON u.user_id = rl.user_id
        WHERE rl.log_id = ?
        """,
        (log_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify(error="Log not found"), 404

    if row["assigned_collector_id"] != collector_id:
        conn.close()
        return jsonify(error="Not authorized for this log"), 403

    if row["status"] != "Assigned":
        conn.close()
        return jsonify(error=f"This request is not Assigned (current: {row['status']})"), 400

    # Optional proof photo (recommended/required when verify)
    proof_url = None
    if uploaded and uploaded.filename:
        filename = secure_filename(uploaded.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        allowed = {"png", "jpg", "jpeg", "gif", "webp"}
        if ext not in allowed:
            conn.close()
            return jsonify(error="Invalid proof image type. Use png/jpg/jpeg/gif/webp."), 400

        upload_dir = os.path.join(current_app.root_path, "static", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        unique = f"collector{collector_id}_log{log_id}_{int(time.time())}_{filename}"
        uploaded.save(os.path.join(upload_dir, unique))
        proof_url = f"uploads/{unique}"

    if action == "verify":
        if not proof_url:
            conn.close()
            return jsonify(error="Proof photo is required to verify."), 400
        cur.execute(
            """
            UPDATE recycling_logs
            SET status='PendingAdmin', collector_proof_url=?, verified_by=?, verified_at=datetime('now'), reject_reason=NULL
            WHERE log_id=?
            """,
            (proof_url, collector_id, log_id),
        )
        cur.execute(
            "INSERT INTO notifications(user_id, message, type) VALUES (?,?,?)",
            (row["resident_id"], "Your recycling submission was verified by a collector and is pending admin approval.", "recycling"),
        )
    else:
        cur.execute(
            """
            UPDATE recycling_logs
            SET status='Rejected', collector_proof_url=COALESCE(?,collector_proof_url), verified_by=?, verified_at=datetime('now'), reject_reason=?
            WHERE log_id=?
            """,
            (proof_url, collector_id, reason or "Rejected by collector", log_id),
        )
        cur.execute(
            "INSERT INTO notifications(user_id, message, type) VALUES (?,?,?)",
            (row["resident_id"], f"Your recycling submission was rejected by a collector. {reason}".strip(), "recycling"),
        )

    conn.commit()
    conn.close()
    return jsonify(ok=True)
