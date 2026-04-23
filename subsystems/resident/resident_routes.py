from flask import Blueprint, request, jsonify, session, current_app
from db import get_db
from subsystems.integration.auth import require_role
from datetime import datetime
import os, time
from werkzeug.utils import secure_filename

resident_bp = Blueprint("resident", __name__)

@resident_bp.get("/api/resident/profile")
def get_profile():
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id,name,email,phone,zone_id FROM users WHERE user_id=?",
        (session["user_id"],),
    )
    row = cur.fetchone()
    conn.close()
    return jsonify(profile=dict(row) if row else None)

@resident_bp.post("/api/resident/profile")
def update_profile():
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    zone_id = int(data.get("zone_id") or 1)

    if not name:
        return jsonify(error="Name cannot be empty."), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET name=?, phone=?, zone_id=? WHERE user_id=?",
        (name, phone, zone_id, session["user_id"]),
    )
    conn.commit()
    conn.close()

    session["name"] = name
    return jsonify(ok=True)

@resident_bp.get("/api/resident/summary")
def summary():
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT total_points, streak_days FROM rewards WHERE user_id=?", (user_id,))
    r = cur.fetchone()

    cur.execute(
        """
        SELECT log_id, waste_type, weight, image_url, created_at, status, points_earned
        FROM recycling_logs
        WHERE user_id=?
        ORDER BY log_id DESC
        LIMIT 5
        """,
        (user_id,),
    )
    logs = [dict(row) for row in cur.fetchall()]
    conn.close()

    return jsonify(
        name=session.get("name"),
        points=(r["total_points"] if r else 0),
        streak_days=(r["streak_days"] if r else 0),
        recent_logs=logs,
    )

@resident_bp.post("/api/resident/recycling_log")
def submit_recycling_log():
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    # --- Read inputs (JSON OR FormData) ---
    if request.is_json:
        data = request.get_json(silent=True) or {}
        waste_type = (data.get("waste_type") or "").strip()
        weight_raw = data.get("weight")
        uploaded = None
    else:
        waste_type = (request.form.get("waste_type") or "").strip()
        weight_raw = request.form.get("weight")
        uploaded = request.files.get("image")

    if not waste_type:
        return jsonify(error="Waste type is required."), 400

    try:
        weight = float(weight_raw)
    except (TypeError, ValueError):
        return jsonify(error="Invalid weight. Please enter a number."), 400

    if weight <= 0:
        return jsonify(error="Weight must be > 0."), 400

    # --- Optional image upload ---
    image_url = ""
    if uploaded and uploaded.filename:
        filename = secure_filename(uploaded.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        allowed = {"png", "jpg", "jpeg", "gif", "webp"}
        if ext not in allowed:
            return jsonify(error="Invalid image type. Use png/jpg/jpeg/gif/webp."), 400

        upload_dir = os.path.join(current_app.root_path, "static", "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        unique = f"u{session['user_id']}_{int(time.time())}_{filename}"
        uploaded.save(os.path.join(upload_dir, unique))
        image_url = f"uploads/{unique}"  # stored in DB

    # --- Reward calculation ---
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT value FROM system_settings WHERE key='reward_rate'")
    row = cur.fetchone()
    reward_rate = float(row["value"]) if row and row["value"] else 10.0
    points_earned = int(round(weight * reward_rate))

    user_id = session["user_id"]
    # Create a reward request.
    # Procedure: Resident submits -> Admin assigns a collector -> Collector verifies (with proof photo)
    # -> Admin approves -> Points credited.
    cur.execute(
        """
        INSERT INTO recycling_logs(user_id, waste_type, weight, image_url, status, points_earned)
        VALUES (?,?,?,?,?,?)
        """,
        (user_id, waste_type, weight, image_url, "Submitted", points_earned),
    )
    cur.execute(
        "INSERT INTO notifications(user_id, message, type) VALUES (?,?,?)",
        (user_id, f"Recycling submitted. Awaiting admin assignment. Estimated +{points_earned} points.", "recycling"),
    )

    conn.commit()
    conn.close()

    return jsonify(ok=True, points_earned=points_earned, status="Submitted", image_url=image_url)




@resident_bp.get("/api/resident/notifications")
def notifications():
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    # ✅ pickup_reminders_enabled
    cur.execute("SELECT value FROM system_settings WHERE key='pickup_reminders_enabled'")
    row = cur.fetchone()
    enabled = (row and row["value"] == "1")

    if enabled:
        # resident zone
        cur.execute("SELECT zone_id FROM users WHERE user_id=?", (user_id,))
        zr = cur.fetchone()
        zone_id = zr["zone_id"] if zr else None

        if zone_id:
            # zone name
            cur.execute("SELECT name FROM zones WHERE zone_id=?", (zone_id,))
            zname = cur.fetchone()
            zone_name = zname["name"] if zname else f"Zone {zone_id}"

            # schedule for zone
            cur.execute("SELECT day, time FROM pickup_schedules WHERE zone_id=? LIMIT 1", (zone_id,))
            ps = cur.fetchone()

            if ps:
                msg = f"Pickup Reminder: {zone_name} pickup is on {ps['day']} at {ps['time']}."

                # prevent duplicates (once per day)
                cur.execute("""
                    SELECT COUNT(*) AS c
                    FROM notifications
                    WHERE user_id=? AND type='pickup_reminder'
                    AND date(created_at)=date('now')
                """, (user_id,))
                already = cur.fetchone()["c"] > 0

                if not already:
                    cur.execute(
                        "INSERT INTO notifications(user_id,message,type) VALUES (?,?,?)",
                        (user_id, msg, "pickup_reminder"),
                    )
                    conn.commit()

    # Return notifications
    cur.execute(
        """
        SELECT notification_id, message, type, created_at, is_read
        FROM notifications
        WHERE user_id=?
        ORDER BY notification_id DESC
        LIMIT 30
        """,
        (user_id,),
    )
    notes = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify(notifications=notes)


@resident_bp.get("/api/resident/notifications/unread_count")
def notifications_unread_count():
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401
    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0", (user_id,))
    c = cur.fetchone()["c"]
    conn.close()
    return jsonify(unread=c)


@resident_bp.post("/api/resident/notifications/mark_all_read")
def notifications_mark_all_read():
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401
    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0", (user_id,))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@resident_bp.get("/api/resident/schedule")
def pickup_schedule():
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT zone_id FROM users WHERE user_id=?", (session["user_id"],))
    zone = cur.fetchone()
    if not zone:
        conn.close()
        return jsonify(schedule=[])

    zone_id = zone["zone_id"]
    cur.execute(
        """
        SELECT ps.day, ps.time, z.name AS zone_name
        FROM pickup_schedules ps
        JOIN zones z ON ps.zone_id = z.zone_id
        WHERE ps.zone_id=?
        ORDER BY ps.schedule_id
        """,
        (zone_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify(schedule=rows)


# ---------------- REWARD STORE (REDEEM) ----------------

@resident_bp.get("/api/resident/rewards/store")
def reward_store():
    """Return available reward items + the resident's current points."""
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT total_points FROM rewards WHERE user_id=?", (user_id,))
    r = cur.fetchone()
    points = r["total_points"] if r else 0

    cur.execute(
        """
        SELECT reward_id, name, cost_points, description
        FROM reward_items
        WHERE is_active=1
        ORDER BY cost_points ASC, reward_id ASC
        """
    )
    items = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(points=points, items=items)


@resident_bp.get("/api/resident/rewards/redemptions")
def reward_redemptions():
    """Return the latest redemptions for the resident."""
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT redemption_id, reward_name, points_spent, status, redeemed_at
        FROM reward_redemptions
        WHERE user_id=?
        ORDER BY redemption_id DESC
        LIMIT 10
        """,
        (user_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(redemptions=rows)


@resident_bp.post("/api/resident/rewards/redeem")
def redeem_reward():
    """Redeem a reward item and deduct points immediately (like your friend's project)."""
    if not require_role("resident"):
        return jsonify(error="Not logged in as resident."), 401

    data = request.get_json(force=True) or {}
    try:
        reward_id = int(data.get("reward_id"))
    except (TypeError, ValueError):
        return jsonify(error="Invalid reward_id."), 400

    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    # Require resident address before redeem (for shipping)
    cur.execute("SELECT COALESCE(address,'') AS address FROM users WHERE user_id=?", (user_id,))
    addr_row = cur.fetchone()
    if not addr_row or not (addr_row["address"] or "").strip():
        conn.close()
        return jsonify(error="Address required before redeem.", code="ADDRESS_REQUIRED"), 400

    # Transaction: validate points, deduct, then insert redemption
    try:
        cur.execute("BEGIN")

        cur.execute(
            "SELECT reward_id, name, cost_points FROM reward_items WHERE reward_id=? AND is_active=1",
            (reward_id,),
        )
        item = cur.fetchone()
        if not item:
            conn.rollback()
            return jsonify(error="Invalid reward selection."), 404

        cur.execute("SELECT total_points FROM rewards WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        current_points = r["total_points"] if r else 0
        cost = int(item["cost_points"])

        if current_points < cost:
            conn.rollback()
            return jsonify(error="Insufficient points."), 400

        # Ensure rewards row exists
        cur.execute(
            "INSERT OR IGNORE INTO rewards(user_id,total_points,streak_days) VALUES (?,?,?)",
            (user_id, 0, 0),
        )
        cur.execute(
            "UPDATE rewards SET total_points = total_points - ? WHERE user_id=?",
            (cost, user_id),
        )

        cur.execute(
            """
            INSERT INTO reward_redemptions(user_id, reward_id, reward_name, points_spent, status)
            VALUES (?,?,?,?,?)
            """,
            (user_id, item["reward_id"], item["name"], cost, "Processing"),
        )

        cur.execute(
            "INSERT INTO notifications(user_id, message, type, is_read) VALUES (?,?,?,0)",
            (user_id, f"Redeemed: {item['name']} (-{cost} points). Waiting for admin approval.", "redeem"),
        )

        conn.commit()

        # return updated balance
        cur.execute("SELECT total_points FROM rewards WHERE user_id=?", (user_id,))
        new_points = cur.fetchone()["total_points"]
        return jsonify(ok=True, new_points=new_points)
    except Exception:
        conn.rollback()
        return jsonify(error="Redeem failed."), 500
    finally:
        conn.close()
