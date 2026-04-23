import sqlite3
from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_db

auth_bp = Blueprint("auth", __name__)

def require_role(*roles) -> bool:
    role = session.get("role")
    return role in roles

@auth_bp.get("/api/me")
def me():
    if "user_id" not in session:
        return jsonify(logged_in=False)
    return jsonify(
        logged_in=True,
        role=session.get("role"),
        name=session.get("name"),
        user_id=session.get("user_id"),
    )

@auth_bp.get("/api/zones")
def list_zones_public():
    """Public list of zones for dropdowns (registration/profile)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT zone_id, name, COALESCE(description,'') AS description FROM zones ORDER BY zone_id")
    zones = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(zones=zones)


@auth_bp.post("/api/register")
def register():
    data = request.get_json(force=True)
    name = (data.get("name") or "Resident").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip()
    zone_raw = (data.get("zone_id") or "").strip()
    if not zone_raw:
        return jsonify(error="Please select a zone."), 400
    try:
        zone_id = int(zone_raw)
    except (TypeError, ValueError):
        return jsonify(error="Invalid zone_id."), 400

    if not email or not password:
        return jsonify(error="Email and password are required."), 400

    if phone and (not phone.isdigit()):
        return jsonify(error="Phone number can only contain digits."), 400

    conn = get_db()
    cur = conn.cursor()

    # validate zone exists
    cur.execute("SELECT zone_id FROM zones WHERE zone_id=?", (zone_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify(error="Selected zone does not exist."), 400

    try:
        cur.execute(
            """
            INSERT INTO users(role,email,password_hash,name,phone,zone_id)
            VALUES (?,?,?,?,?,?)
            """,
            ("resident", email, generate_password_hash(password), name, phone, zone_id),
        )
        user_id = cur.lastrowid
        cur.execute(
            "INSERT OR IGNORE INTO rewards(user_id,total_points,streak_days) VALUES (?,?,?)",
            (user_id, 0, 0),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="This email is already registered."), 409
    finally:
        conn.close()

    return jsonify(ok=True)


@auth_bp.post("/api/login")
def login():
    data = request.get_json(force=True)
    role = data.get("role")
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if role not in ("resident", "collector", "admin"):
        return jsonify(error="Please select a valid role."), 400
    if not email or not password:
        return jsonify(error="Email and password are required."), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id,password_hash,name FROM users WHERE email=? AND role=?",
        (email, role),
    )
    user = cur.fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Invalid email/password/role."), 401

    session["user_id"] = user["user_id"]
    session["role"] = role
    session["name"] = user["name"]
    return jsonify(ok=True, role=role, name=user["name"])


@auth_bp.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# ------------------------------
# Profile (all roles)
# ------------------------------

@auth_bp.get("/api/profile")
def get_profile():
    if "user_id" not in session:
        return jsonify(error="Not logged in."), 401
    uid = session["user_id"]
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, role, email, name, phone,
               COALESCE(address,'') AS address,
               COALESCE(address_place,'') AS address_place,
               address_lat, address_lng,
               zone_id
        FROM users WHERE user_id=?
        """,
        (uid,),
    )
    u = cur.fetchone()
    conn.close()
    if not u:
        return jsonify(error="User not found."), 404

    profile = dict(u)
    # Include zone name for residents, and assigned zones list for collectors
    conn = get_db()
    cur = conn.cursor()
    try:
        if profile.get("role") == "resident":
            zid = profile.get("zone_id")
            if zid:
                cur.execute("SELECT name FROM zones WHERE zone_id=?", (zid,))
                r = cur.fetchone()
                profile["zone_name"] = r["name"] if r else ""
            else:
                profile["zone_name"] = ""
        elif profile.get("role") == "collector":
            cur.execute("SELECT zone_id FROM collector_assignments WHERE collector_id=? ORDER BY zone_id", (profile["user_id"],))
            profile["collector_zones"] = [row["zone_id"] for row in cur.fetchall()]
        else:
            profile["collector_zones"] = []
    finally:
        conn.close()

    return jsonify(profile=profile)


@auth_bp.post("/api/profile")
def update_profile():
    """Update name/phone for any role; update address only for residents."""
    if "user_id" not in session:
        return jsonify(error="Not logged in."), 401
    uid = session["user_id"]
    role = session.get("role")
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    address = (data.get("address") or "").strip()
    address_place = (data.get("address_place") or "").strip()
    address_lat = data.get("address_lat")
    address_lng = data.get("address_lng")
    zone_raw = (data.get("zone_id") or "").strip()

    if not name:
        return jsonify(error="Name cannot be empty."), 400

    if phone and (not phone.isdigit()):
        return jsonify(error="Phone number can only contain digits."), 400

    conn = get_db()
    cur = conn.cursor()
    if role == "resident":
        if not zone_raw:
            conn.close()
            return jsonify(error="Please select your zone."), 400
        try:
            zone_id = int(zone_raw)
        except (TypeError, ValueError):
            conn.close()
            return jsonify(error="Invalid zone_id."), 400

        # validate zone exists
        cur.execute("SELECT zone_id FROM zones WHERE zone_id=?", (zone_id,))
        if not cur.fetchone():
            conn.close()
            return jsonify(error="Selected zone does not exist."), 400

        cur.execute(
            """
            UPDATE users
            SET name=?, phone=?, address=?, address_place=?, address_lat=?, address_lng=?, zone_id=?
            WHERE user_id=?
            """,
            (name, phone, address, address_place, address_lat, address_lng, zone_id, uid),
        )
    else:
        cur.execute(
            "UPDATE users SET name=?, phone=? WHERE user_id=?",
            (name, phone, uid),
        )
    conn.commit()
    conn.close()

    # Keep session name in sync
    session["name"] = name
    return jsonify(ok=True)
