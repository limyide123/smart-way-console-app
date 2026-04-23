from flask import Flask, render_template, session, redirect

# Ensure DB schema is up to date (adds columns like users.address)
import migrate_db

from subsystems.integration.auth import auth_bp
from subsystems.resident.resident_routes import resident_bp
from subsystems.collector.collector_routes import collector_bp
from subsystems.admin.admin_routes import admin_bp

app = Flask(__name__)
app.secret_key = "change-this-to-a-random-secret"

# Run schema migration on startup (safe: CREATE TABLE IF NOT EXISTS + column adds)
try:
    migrate_db.main()
except Exception as e:
    # Don't crash the app if migration printing fails; the app may still run.
    print("DB migration warning:", e)

@app.get("/")
def index():
    return render_template("index.html")


def _guard(*roles):
    """Return a redirect response if user isn't in one of the roles."""
    if session.get("role") not in roles:
        return redirect("/")
    return None


# -------- Page routes (phone-style pages) --------

@app.get("/resident/home")
def resident_home_page():
    bad = _guard("resident")
    if bad:
        return bad
    return render_template("resident_home.html")


@app.get("/resident/profile")
def resident_profile_page():
    bad = _guard("resident")
    if bad:
        return bad
    return render_template("profile.html", role="resident")


@app.get("/resident/address")
def resident_address_page():
    bad = _guard("resident")
    if bad:
        return bad
    return render_template("resident_address.html")


@app.get("/resident/recycle")
def resident_recycle_page():
    bad = _guard("resident")
    if bad:
        return bad
    return render_template("resident_recycle.html")


@app.get("/resident/notifications")
def resident_notifications_page():
    bad = _guard("resident")
    if bad:
        return bad
    return render_template("resident_notifications.html")


@app.get("/collector/home")
def collector_home_page():
    bad = _guard("collector")
    if bad:
        return bad
    return render_template("collector_home.html")


@app.get("/collector/profile")
def collector_profile_page():
    bad = _guard("collector")
    if bad:
        return bad
    return render_template("profile.html", role="collector")


@app.get("/collector/schedule")
def collector_schedule_page():
    bad = _guard("collector")
    if bad:
        return bad
    return render_template("collector_schedule.html")


@app.get("/collector/rewards")
def collector_rewards_page():
    bad = _guard("collector")
    if bad:
        return bad
    return render_template("collector_rewards.html")


@app.get("/collector/route")
def collector_route_page():
    bad = _guard("collector")
    if bad:
        return bad
    return render_template("collector_route.html")


@app.get("/collector/status")
def collector_status_page():
    bad = _guard("collector")
    if bad:
        return bad
    return render_template("collector_status.html")


@app.get("/collector/issue")
def collector_issue_page():
    bad = _guard("collector")
    if bad:
        return bad
    return render_template("collector_issue.html")


@app.get("/admin/home")
def admin_home_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_home.html")


@app.get("/admin/profile")
def admin_profile_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("profile.html", role="admin")


@app.get("/admin/residents")
def admin_residents_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_users.html", user_role="resident")


@app.get("/admin/collectors")
def admin_collectors_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_users.html", user_role="collector")


@app.get("/admin/zones")
def admin_zones_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_zones.html")


@app.get("/admin/approvals")
def admin_approvals_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_approvals.html")


@app.get("/admin/assign")
def admin_assign_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_assign.html")


@app.get("/admin/redeems")
def admin_redeems_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_redeems.html")


@app.get("/admin/schedules")
def admin_schedules_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_schedules.html")


@app.get("/admin/notify")
def admin_notify_page():
    bad = _guard("admin")
    if bad:
        return bad
    return render_template("admin_notify.html")


@app.get("/resident/rewards")
def resident_rewards_page():
    # Simple guard so non-residents don't land on this page
    if session.get("role") != "resident":
        return redirect("/")
    return render_template("resident_rewards.html")

# Register subsystems (Blueprints)
app.register_blueprint(auth_bp)
app.register_blueprint(resident_bp)
app.register_blueprint(collector_bp)
app.register_blueprint(admin_bp)

if __name__ == "__main__":
    app.run(debug=True)
