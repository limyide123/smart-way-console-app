from flask import Blueprint, request, jsonify, session, render_template
from db import get_db
from subsystems.integration.auth import require_role

admin_bp = Blueprint("admin", __name__)


# ------------------------------
# Admin: assign collector to a submitted recycling log
# ------------------------------


@admin_bp.get("/api/admin/recycling/submitted")
def submitted_logs():
    """Logs submitted by residents that are waiting for admin to assign a collector."""
    if not require_role("admin"):
        return jsonify(error="Not logged in as admin."), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rl.log_id, rl.created_at, rl.waste_type, rl.weight, rl.image_url,
               rl.status, rl.points_earned,
               u.user_id AS resident_id, u.name AS resident_name, u.phone AS resident_phone,
               u.zone_id, z.name AS zone_name
        FROM recycling_logs rl
        JOIN users u ON u.user_id = rl.user_id
        JOIN zones z ON z.zone_id = u.zone_id
        WHERE rl.status = 'Submitted'
        ORDER BY rl.log_id DESC
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(requests=rows)


@admin_bp.post("/api/admin/recycling/<int:log_id>/assign")
def assign_collector_to_log(log_id: int):
    """Assign a collector to a specific recycling log.

    Body JSON: {"collector_id": 2}
    """
    if not require_role("admin"):
        return jsonify(error="Not logged in as admin."), 401

    data = request.get_json(silent=True) or {}
    try:
        collector_id = int(data.get("collector_id"))
    except (TypeError, ValueError):
        collector_id = None
    if not collector_id:
        return jsonify(error="collector_id is required"), 400

    admin_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    # Validate log
    cur.execute(
        """
        SELECT rl.log_id, rl.user_id AS resident_id, rl.status, u.zone_id
        FROM recycling_logs rl
        JOIN users u ON u.user_id = rl.user_id
        WHERE rl.log_id=?
        """,
        (log_id,),
    )
    log = cur.fetchone()
    if not log:
        conn.close()
        return jsonify(error="Log not found"), 404
    if log["status"] != "Submitted":
        conn.close()
        return jsonify(error=f"This log is not Submitted (current: {log['status']})"), 400

    # Validate collector exists and is allowed for the resident's zone (must be assigned to zone)
    cur.execute("SELECT user_id, name FROM users WHERE user_id=? AND role='collector'", (collector_id,))
    c = cur.fetchone()
    if not c:
        conn.close()
        return jsonify(error="Collector not found"), 404

    cur.execute(
        """
        SELECT 1 FROM collector_assignments
        WHERE collector_id=? AND zone_id=?
        """,
        (collector_id, log["zone_id"]),
    )
    if not cur.fetchone():
        conn.close()
        return jsonify(error="Collector is not assigned to the resident's zone"), 400

    # Assign
    cur.execute(
        """
        UPDATE recycling_logs
        SET status='Assigned', assigned_collector_id=?, assigned_by=?, assigned_at=datetime('now')
        WHERE log_id=?
        """,
        (collector_id, admin_id, log_id),
    )

    # Notify resident + collector
    cur.execute(
        "INSERT INTO notifications(user_id, message, type) VALUES (?,?,?)",
        (log["resident_id"], "Admin assigned a collector. Awaiting collection and verification.", "recycling"),
    )
    cur.execute(
        "INSERT INTO notifications(user_id, message, type) VALUES (?,?,?)",
        (collector_id, f"New collection assigned: Recycling Log #{log_id}. Please collect and upload proof to verify.", "recycling"),
    )

    conn.commit()
    conn.close()
    return jsonify(ok=True)


@admin_bp.get("/api/admin/zones/<int:zone_id>/collectors")
def collectors_for_zone(zone_id: int):
    """List collectors assigned to the given zone (for assignment dropdown)."""
    if not require_role("admin"):
        return jsonify(error="Not logged in as admin."), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT u.user_id, u.name, u.phone
        FROM users u
        JOIN collector_assignments ca ON ca.collector_id = u.user_id
        WHERE u.role='collector' AND ca.zone_id=?
        GROUP BY u.user_id
        ORDER BY u.user_id
        """,
        (zone_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(collectors=rows)


# ------------------------------
# Admin pages (simple navigation)
# ------------------------------


@admin_bp.get("/admin/zones/<int:zone_id>")
def admin_zone_page(zone_id: int):
    """A dedicated Zone Management page (requested UI navigation)."""
    if not require_role("admin"):
        # Keep it simple: show the login page if not admin.
        return render_template("index.html")
    return render_template("admin_zone.html", zone_id=zone_id)

@admin_bp.get("/api/admin/summary")
def summary():
    if not require_role("admin"):
        return jsonify(error="Not logged in as admin."), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM recycling_logs")
    total_logs = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(weight),0) AS s FROM recycling_logs")
    total_weight = cur.fetchone()["s"]
    conn.close()

    return jsonify(
        name=session.get("name"),
        total_logs=total_logs,
        total_weight=total_weight,
    )


# ------------------------------
# Admin: view users (residents / collectors)
# ------------------------------

@admin_bp.get("/api/admin/users")
def admin_list_users():
    if not require_role("admin"):
        return jsonify(error="Not logged in as admin."), 401

    role = (request.args.get("role") or "").strip().lower()
    if role not in {"resident", "collector"}:
        return jsonify(error="role must be 'resident' or 'collector'"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT u.user_id, u.role, u.name, u.phone, COALESCE(u.address,'') AS address, u.email, u.zone_id,
               (SELECT cs.status FROM collection_status cs WHERE cs.collector_id=u.user_id ORDER BY cs.created_at DESC, cs.status_id DESC LIMIT 1) AS latest_status,
               (SELECT cs.created_at FROM collection_status cs WHERE cs.collector_id=u.user_id ORDER BY cs.created_at DESC, cs.status_id DESC LIMIT 1) AS latest_status_at,
               (SELECT cs.zone_id FROM collection_status cs WHERE cs.collector_id=u.user_id ORDER BY cs.created_at DESC, cs.status_id DESC LIMIT 1) AS latest_status_zone_id
        FROM users u
        WHERE u.role=?
        ORDER BY u.user_id
        """,
        (role,),
    )
    users = [dict(u) for u in cur.fetchall()]
    conn.close()
    return jsonify(users=users)


# ------------------------------
# Admin: send notifications to users
# ------------------------------

@admin_bp.post("/api/admin/notify")
def admin_send_notification():
    if not require_role("admin"):
        return jsonify(error="Not logged in as admin."), 401

    data = request.get_json(silent=True) or {}
    # Notifications: admin can send to residents only (no collectors).
    user_id = data.get("user_id")
    role = (data.get("role") or "").strip().lower()
    message = (data.get("message") or "").strip()
    ntype = (data.get("type") or "admin").strip() or "admin"

    if not message:
        return jsonify(error="Message cannot be empty."), 400

    conn = get_db()
    cur = conn.cursor()

    try:
        if user_id is not None and str(user_id).strip() != "":
            try:
                uid = int(user_id)
            except (TypeError, ValueError):
                return jsonify(error="Invalid user_id"), 400
            cur.execute("SELECT user_id, role FROM users WHERE user_id=?", (uid,))
            row = cur.fetchone()
            if not row:
                return jsonify(error="User not found"), 404
            if row["role"] != "resident":
                return jsonify(error="Notifications can only be sent to residents."), 400
            cur.execute(
                "INSERT INTO notifications(user_id,message,type,is_read) VALUES (?,?,?,0)",
                (uid, message, ntype),
            )
            conn.commit()
            return jsonify(ok=True, sent=1)

        # role-mode: default to residents only
        if role and role != "resident":
            return jsonify(error="Notifications can only be sent to residents."), 400

        cur.execute("SELECT user_id FROM users WHERE role='resident'")
        ids = [r["user_id"] for r in cur.fetchall()]
        for uid in ids:
            cur.execute(
                "INSERT INTO notifications(user_id,message,type,is_read) VALUES (?,?,?,0)",
                (uid, message, ntype),
            )
        conn.commit()
        return jsonify(ok=True, sent=len(ids))
    finally:
        conn.close()


# ------------------------------
# Rewards approval workflow
# ------------------------------

@admin_bp.get("/api/admin/rewards/pending")
def pending_reward_approvals():
    """Admin views collector-verified requests awaiting final approval."""
    if not require_role("admin"):
        return jsonify(error="Not logged in as admin."), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rl.log_id, rl.created_at, rl.waste_type, rl.weight, rl.image_url,
               rl.collector_proof_url,
               rl.status, rl.points_earned, rl.verified_by, rl.verified_at,
               rl.assigned_collector_id, rl.assigned_at,
               u.user_id AS resident_id, u.name AS resident_name, u.zone_id,
               z.name AS zone_name,
               c.name AS verified_by_name
        FROM recycling_logs rl
        JOIN users u ON u.user_id = rl.user_id
        JOIN zones z ON z.zone_id = u.zone_id
        LEFT JOIN users c ON c.user_id = rl.verified_by
        WHERE rl.status = 'PendingAdmin'
        ORDER BY rl.log_id DESC
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(requests=rows)


@admin_bp.post("/api/admin/rewards/<int:log_id>/decision")
def decide_reward_request(log_id: int):
    """Admin approves or rejects a verified reward request.

    Body JSON:
      {"action": "approve"|"reject", "reason": "optional"}
    """
    if not require_role("admin"):
        return jsonify(error="Not logged in as admin."), 401

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    reason = (data.get("reason") or "").strip()
    if action not in {"approve", "reject"}:
        return jsonify(error="action must be 'approve' or 'reject'"), 400

    admin_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT log_id, user_id, status, points_earned
        FROM recycling_logs
        WHERE log_id=?
        """,
        (log_id,),
    )
    log = cur.fetchone()
    if not log:
        conn.close()
        return jsonify(error="Log not found"), 404

    if log["status"] != "PendingAdmin":
        conn.close()
        return jsonify(error=f"This request is not PendingAdmin (current: {log['status']})"), 400

    resident_id = log["user_id"]
    points = int(log["points_earned"] or 0)

    if action == "approve":
        # Award points
        cur.execute(
            "UPDATE rewards SET total_points = total_points + ? WHERE user_id=?",
            (points, resident_id),
        )
        cur.execute(
            """
            UPDATE recycling_logs
            SET status='Approved', approved_by=?, approved_at=datetime('now'), reject_reason=NULL
            WHERE log_id=?
            """,
            (admin_id, log_id),
        )
        cur.execute(
            "INSERT INTO notifications(user_id, message, type) VALUES (?,?,?)",
            (resident_id, f"Your recycling points were approved! +{points} points added.", "recycling"),
        )
    else:
        cur.execute(
            """
            UPDATE recycling_logs
            SET status='Rejected', approved_by=?, approved_at=datetime('now'), reject_reason=?
            WHERE log_id=?
            """,
            (admin_id, reason or "Rejected by admin", log_id),
        )
        cur.execute(
            "INSERT INTO notifications(user_id, message, type) VALUES (?,?,?)",
            (resident_id, f"Your recycling points request was rejected by admin. {reason}".strip(), "recycling"),
        )

    conn.commit()
    conn.close()
    return jsonify(ok=True)

# ---- ZONE MANAGEMENT (CRUD) ----
@admin_bp.get("/api/admin/zones")
def get_zones():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT zone_id,name,description FROM zones ORDER BY zone_id")
    zones = [dict(z) for z in cur.fetchall()]
    conn.close()
    return jsonify(zones=zones)


@admin_bp.get("/api/admin/zones/<int:zone_id>")
def get_zone(zone_id: int):
    """Get a single zone (used by the dedicated Zone page UI)."""
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT zone_id,name,description FROM zones WHERE zone_id=?", (zone_id,))
    z = cur.fetchone()
    conn.close()
    if not z:
        return jsonify(error="Zone not found"), 404
    return jsonify(zone=dict(z))

@admin_bp.post("/api/admin/zones")
def add_zone():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    if not name:
        return jsonify(error="Zone name required"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO zones(name,description) VALUES (?,?)", (name, description))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

@admin_bp.put("/api/admin/zones/<int:zone_id>")
def edit_zone(zone_id: int):
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    if not name:
        return jsonify(error="Zone name required"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE zones SET name=?, description=? WHERE zone_id=?",
        (name, description, zone_id),
    )
    conn.commit()
    conn.close()
    return jsonify(ok=True)

@admin_bp.delete("/api/admin/zones/<int:zone_id>")
def delete_zone(zone_id: int):
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM zones WHERE zone_id=?", (zone_id,))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

# ---- ASSIGN COLLECTORS ----
@admin_bp.post("/api/admin/assign")
def assign_collector():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(force=True)
    collector_id = data.get("collector_id")
    zone_id = data.get("zone_id")

    if not collector_id or not zone_id:
        return jsonify(error="collector_id and zone_id required"), 400

    conn = get_db()
    cur = conn.cursor()

    # Validate collector + zone
    cur.execute("SELECT user_id FROM users WHERE user_id=? AND role='collector'", (collector_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify(error="collector_id is not a valid collector"), 400
    cur.execute("SELECT zone_id FROM zones WHERE zone_id=?", (zone_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify(error="zone_id not found"), 404

    # Prevent duplicate assignment
    cur.execute(
        "SELECT 1 FROM collector_assignments WHERE collector_id=? AND zone_id=?",
        (collector_id, zone_id),
    )
    if cur.fetchone():
        conn.close()
        return jsonify(error="This collector already has this zone assigned."), 409

    # 1) Add assignment
    cur.execute(
        """
        INSERT INTO collector_assignments(collector_id, zone_id, assigned_date)
        VALUES (?,?,date('now'))
        """,
        (collector_id, zone_id),
    )

    # 2) Auto-generate an "optimized route"
    #    (simple optimization: order zones by zone_id)
    cur.execute("""
        SELECT z.zone_id, z.name
        FROM collector_assignments ca
        JOIN zones z ON ca.zone_id = z.zone_id
        WHERE ca.collector_id = ?
        ORDER BY z.zone_id
    """, (collector_id,))
    zones = cur.fetchall()

    if zones:
        # Example optimized route format:
        # Zone A -> Zone B -> Zone C (Auto-Optimized)
        path = " -> ".join([z["name"] for z in zones]) + " (Auto-Optimized)"

        # Save new route (overwrite today's route for simplicity)
        cur.execute("""
            DELETE FROM routes
            WHERE collector_id=?
        """, (collector_id,))

        cur.execute("""
            INSERT INTO routes(collector_id, route_date, optimized_path)
            VALUES (?, date('now'), ?)
        """, (collector_id, path))

    conn.commit()
    conn.close()

    return jsonify(ok=True, message="Collector assigned and route updated automatically.")


# ------------------------------
# Reward Store Management (Admin)
# ------------------------------


@admin_bp.get("/api/admin/reward_items")
def admin_reward_items_list():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT reward_id, name, cost_points, description, is_active
        FROM reward_items
        ORDER BY reward_id DESC
        """
    )
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(items=items)


@admin_bp.post("/api/admin/reward_items")
def admin_reward_items_add():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    try:
        cost_points = int(data.get("cost_points"))
    except (TypeError, ValueError):
        cost_points = None
    is_active = 1 if str(data.get("is_active", "1")).strip() != "0" else 0

    if not name or cost_points is None or cost_points <= 0:
        return jsonify(error="name and positive cost_points are required"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reward_items(name,cost_points,description,is_active) VALUES (?,?,?,?)",
        (name, cost_points, description, is_active),
    )
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@admin_bp.put("/api/admin/reward_items/<int:reward_id>")
def admin_reward_items_update(reward_id: int):
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    try:
        cost_points = int(data.get("cost_points"))
    except (TypeError, ValueError):
        cost_points = None
    is_active = 1 if str(data.get("is_active", "1")).strip() != "0" else 0

    if not name or cost_points is None or cost_points <= 0:
        return jsonify(error="name and positive cost_points are required"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE reward_items SET name=?, cost_points=?, description=?, is_active=? WHERE reward_id=?",
        (name, cost_points, description, is_active, reward_id),
    )
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@admin_bp.delete("/api/admin/reward_items/<int:reward_id>")
def admin_reward_items_delete(reward_id: int):
    """Soft-delete: hide item from store by setting is_active=0 (keeps history safe)."""
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE reward_items SET is_active=0 WHERE reward_id=?", (reward_id,))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


# ------------------------------
# Redemption Status (Processing -> Claimed)
# ------------------------------


@admin_bp.get("/api/admin/redemptions")
def admin_redemptions_list():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rr.redemption_id, rr.reward_name, rr.points_spent, rr.status, rr.redeemed_at,
               u.user_id AS resident_id, u.name AS resident_name
        FROM reward_redemptions rr
        JOIN users u ON u.user_id = rr.user_id
        ORDER BY rr.redemption_id DESC
        LIMIT 50
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(redemptions=rows)


@admin_bp.post("/api/admin/redemptions/<int:redemption_id>/claim")
def admin_redemption_claim(redemption_id: int):
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT redemption_id, user_id, reward_name, status FROM reward_redemptions WHERE redemption_id=?",
        (redemption_id,),
    )
    r = cur.fetchone()
    if not r:
        conn.close()
        return jsonify(error="Redemption not found"), 404

    if r["status"] == "Claimed":
        conn.close()
        return jsonify(ok=True)

    cur.execute(
        "UPDATE reward_redemptions SET status='Claimed' WHERE redemption_id=?",
        (redemption_id,),
    )
    cur.execute(
        "INSERT INTO notifications(user_id,message,type,is_read) VALUES (?,?,?,0)",
        (r["user_id"], f"Redeem approved: '{r['reward_name']}'. We will send it to your house within 7 working days.", "redeem"),
    )
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@admin_bp.post("/api/admin/redemptions/<int:redemption_id>/reject")
def admin_redemption_reject(redemption_id: int):
    """Reject a redemption and refund points to the resident."""
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip() or "Rejected by admin"

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute(
            """
            SELECT redemption_id, user_id, reward_name, points_spent, status
            FROM reward_redemptions
            WHERE redemption_id=?
            """,
            (redemption_id,),
        )
        r = cur.fetchone()
        if not r:
            conn.rollback()
            return jsonify(error="Redemption not found"), 404

        if r["status"] == "Rejected":
            conn.rollback()
            return jsonify(ok=True)

        # Mark rejected
        cur.execute(
            "UPDATE reward_redemptions SET status='Rejected' WHERE redemption_id=?",
            (redemption_id,),
        )

        # Refund points
        cur.execute(
            "INSERT OR IGNORE INTO rewards(user_id,total_points,streak_days) VALUES (?,?,?)",
            (r["user_id"], 0, 0),
        )
        cur.execute(
            "UPDATE rewards SET total_points = total_points + ? WHERE user_id=?",
            (int(r["points_spent"]), r["user_id"]),
        )

        cur.execute(
            "INSERT INTO notifications(user_id,message,type,is_read) VALUES (?,?,?,0)",
            (r["user_id"], f"Redeem rejected: '{r['reward_name']}'. {reason}. Points refunded (+{int(r['points_spent'])}).", "redeem"),
        )

        conn.commit()
        return jsonify(ok=True)
    except Exception:
        conn.rollback()
        return jsonify(error="Reject failed"), 500
    finally:
        conn.close()


# ---- PICKUP SCHEDULES ----
@admin_bp.get("/api/admin/schedules")
def schedules():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ps.schedule_id, z.zone_id, z.name AS zone_name, ps.day, ps.time
        FROM pickup_schedules ps
        JOIN zones z ON ps.zone_id = z.zone_id
        ORDER BY z.zone_id, ps.schedule_id
        """
    )
    schedules = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(schedules=schedules)

@admin_bp.post("/api/admin/schedules")
def add_schedule():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(force=True)
    zone_id = data.get("zone_id")
    day = (data.get("day") or "").strip()
    time = (data.get("time") or "").strip()

    if not zone_id or not day or not time:
        return jsonify(error="zone_id, day, time required"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO pickup_schedules(zone_id,day,time) VALUES (?,?,?)", (zone_id, day, time))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@admin_bp.get("/api/admin/zones/<int:zone_id>/schedules")
def zone_schedules(zone_id: int):
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT schedule_id, zone_id, day, time
        FROM pickup_schedules
        WHERE zone_id=?
        ORDER BY schedule_id
        """,
        (zone_id,),
    )
    schedules = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(schedules=schedules)


@admin_bp.delete("/api/admin/schedules/<int:schedule_id>")
def delete_schedule(schedule_id: int):
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM pickup_schedules WHERE schedule_id=?", (schedule_id,))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

# ---- BIN ISSUES ----
@admin_bp.get("/api/admin/issues")
def issues():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT bi.issue_id, u.name AS collector, z.name AS zone, bi.issue_type, bi.created_at
        FROM bin_issues bi
        JOIN users u ON bi.collector_id = u.user_id
        JOIN zones z ON bi.zone_id = z.zone_id
        ORDER BY bi.issue_id DESC
        LIMIT 50
        """
    )
    issues = [dict(i) for i in cur.fetchall()]
    conn.close()
    return jsonify(issues=issues)

# ---- SYSTEM SETTINGS ----


@admin_bp.get("/admin/settings")
def admin_settings_page():
    """Admin UI page for system settings (reward rate, pickup reminders toggle)."""
    if not require_role("admin"):
        # keep it consistent with other pages
        return render_template("index.html")
    return render_template("admin_settings.html")


@admin_bp.get("/api/admin/settings")
def get_settings():
    """Fetch current system settings."""
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM system_settings WHERE key IN ('reward_rate','pickup_reminders_enabled')")
    rows = {r["key"]: r["value"] for r in cur.fetchall()}
    conn.close()

    # defaults (also seeded in migrate_db.py)
    return jsonify(
        settings={
            "reward_rate": rows.get("reward_rate", "10"),
            "pickup_reminders_enabled": rows.get("pickup_reminders_enabled", "1"),
        }
    )


@admin_bp.post("/api/admin/settings")
def save_setting():
    if not require_role("admin"):
        return jsonify(error="Unauthorized"), 401

    data = request.get_json(force=True)
    key = (data.get("key") or "").strip()
    value = (data.get("value") or "").strip()

    if key not in ("reward_rate", "pickup_reminders_enabled"):
        return jsonify(error="Invalid setting key"), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO system_settings(key,value)
      VALUES (?,?)
      ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))
    conn.commit()
    conn.close()

    return jsonify(ok=True)
