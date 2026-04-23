import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = "smart_waste.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Core users table (with name + phone + address info)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL CHECK(role IN ('resident','collector','admin')),
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT 'User',
        phone TEXT DEFAULT '',
        -- Resident extra info (kept here for simple display/edit)
        address TEXT DEFAULT '',
        address_place TEXT DEFAULT '',
        address_lat REAL,
        address_lng REAL,
        zone_id INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS rewards (
        user_id INTEGER PRIMARY KEY,
        total_points INTEGER NOT NULL DEFAULT 0,
        streak_days INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS recycling_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        waste_type TEXT NOT NULL,
        weight REAL NOT NULL,
        image_url TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        -- Reward approval workflow
        status TEXT NOT NULL DEFAULT 'Submitted',
        points_earned INTEGER NOT NULL DEFAULT 0,

        -- Admin assignment (who will collect & verify)
        assigned_collector_id INTEGER,
        assigned_by INTEGER,
        assigned_at TEXT,
        collect_date TEXT,

        -- Collector validation proof photo
        collector_proof_url TEXT,
        verified_by INTEGER,
        verified_at TEXT,
        approved_by INTEGER,
        approved_at TEXT,
        reject_reason TEXT,
        FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """)

    # --- Lightweight schema upgrades for existing DBs (SQLite ALTER TABLE) ---
    def ensure_column(table, col_name, col_def_sql):
        cur.execute(f"PRAGMA table_info({table})")
        cols = {r[1] for r in cur.fetchall()}  # (cid, name, type, notnull, dflt_value, pk)
        if col_name not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_def_sql}")

    ensure_column('recycling_logs', 'status', "status TEXT NOT NULL DEFAULT 'Submitted'")
    ensure_column('recycling_logs', 'points_earned', "points_earned INTEGER NOT NULL DEFAULT 0")
    ensure_column('recycling_logs', 'assigned_collector_id', "assigned_collector_id INTEGER")
    ensure_column('recycling_logs', 'assigned_by', "assigned_by INTEGER")
    ensure_column('recycling_logs', 'assigned_at', "assigned_at TEXT")
    ensure_column('recycling_logs', 'collect_date', "collect_date TEXT")
    ensure_column('recycling_logs', 'collector_proof_url', "collector_proof_url TEXT")
    ensure_column('recycling_logs', 'verified_by', "verified_by INTEGER")
    ensure_column('recycling_logs', 'verified_at', "verified_at TEXT")
    ensure_column('recycling_logs', 'approved_by', "approved_by INTEGER")
    ensure_column('recycling_logs', 'approved_at', "approved_at TEXT")
    ensure_column('recycling_logs', 'reject_reason', "reject_reason TEXT")

    # User profile upgrades (address columns)
    ensure_column('users', 'address', "address TEXT DEFAULT ''")
    ensure_column('users', 'address_place', "address_place TEXT DEFAULT ''")
    ensure_column('users', 'address_lat', "address_lat REAL")
    ensure_column('users', 'address_lng', "address_lng REAL")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        type TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        is_read INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """)

    ensure_column('notifications', 'is_read', "is_read INTEGER NOT NULL DEFAULT 0")

    # Zones + schedules + routes + assignments
    cur.execute("""
    CREATE TABLE IF NOT EXISTS zones (
      zone_id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      description TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS collector_assignments (
      assign_id INTEGER PRIMARY KEY AUTOINCREMENT,
      collector_id INTEGER,
      zone_id INTEGER,
      assigned_date TEXT,
      FOREIGN KEY(collector_id) REFERENCES users(user_id),
      FOREIGN KEY(zone_id) REFERENCES zones(zone_id)
    )
    """)

    # Try to prevent duplicates (best-effort): add unique index if not exists.
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_collector_zone_unique ON collector_assignments(collector_id, zone_id)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pickup_schedules (
      schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
      zone_id INTEGER,
      day TEXT,
      time TEXT,
      FOREIGN KEY(zone_id) REFERENCES zones(zone_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS routes (
      route_id INTEGER PRIMARY KEY AUTOINCREMENT,
      collector_id INTEGER,
      route_date TEXT,
      optimized_path TEXT,
      FOREIGN KEY(collector_id) REFERENCES users(user_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS collection_status (
      status_id INTEGER PRIMARY KEY AUTOINCREMENT,
      collector_id INTEGER,
      zone_id INTEGER,
      status TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bin_issues (
      issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
      collector_id INTEGER,
      zone_id INTEGER,
      issue_type TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # System settings
    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
    """)

    # Reward store catalogue + redemption history (Resident redeem feature)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reward_items (
      reward_id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      cost_points INTEGER NOT NULL,
      description TEXT DEFAULT '',
      is_active INTEGER NOT NULL DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reward_redemptions (
      redemption_id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      reward_id INTEGER,
      reward_name TEXT NOT NULL,
      points_spent INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'Processing',
      redeemed_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
      FOREIGN KEY(reward_id) REFERENCES reward_items(reward_id)
    )
    """)

    # Seed settings
    cur.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES ('reward_rate','10')")
    cur.execute("INSERT OR IGNORE INTO system_settings(key,value) VALUES ('pickup_reminders_enabled','1')")

    # Seed reward store items (if empty)
    cur.execute("SELECT COUNT(*) FROM reward_items")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO reward_items(name,cost_points,description) VALUES (?,?,?)",
            ("Eco Tote Bag", 100, "Reusable tote bag")
        )
        cur.execute(
            "INSERT INTO reward_items(name,cost_points,description) VALUES (?,?,?)",
            ("RM10 Cash Voucher", 250, "Digital voucher")
        )
        cur.execute(
            "INSERT INTO reward_items(name,cost_points,description) VALUES (?,?,?)",
            ("Recycling Bin Kit", 500, "Starter kit for sorting")
        )

    # Seed zones
    cur.execute("SELECT COUNT(*) FROM zones")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO zones(name,description) VALUES ('Zone A','Residential Area A')")
        cur.execute("INSERT INTO zones(name,description) VALUES ('Zone B','Residential Area B')")

    # Seed demo accounts
    def ensure_user(role, email, pw, name):
        cur.execute("SELECT user_id FROM users WHERE email=? AND role=?", (email, role))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "INSERT INTO users(role,email,password_hash,name,phone,zone_id) VALUES (?,?,?,?,?,?)",
            (role, email, generate_password_hash(pw), name, "", None)
        )
        return cur.lastrowid

    rid = ensure_user("resident", "alice@gmail.com", "resident123", "Alice Tan")
    # set Alice to Zone A by default (can be changed in profile)
    cur.execute("UPDATE users SET zone_id=1 WHERE user_id=?", (rid,))
    cid = ensure_user("collector", "john.collector@mail.com", "collector123", "John Lim")
    # collectors start with no default zone_id; assignment is done by admin
    cur.execute("UPDATE users SET zone_id=NULL WHERE user_id=?", (cid,))
    ensure_user("admin", "admin@municipal.gov", "admin123", "Admin One")

    cur.execute("INSERT OR IGNORE INTO rewards(user_id,total_points,streak_days) VALUES (?,?,?)",
                (rid, 0, 0))

    # Seed pickup schedules
    cur.execute("SELECT COUNT(*) FROM pickup_schedules")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO pickup_schedules(zone_id,day,time) VALUES (1,'Monday','09:00')")
        cur.execute("INSERT INTO pickup_schedules(zone_id,day,time) VALUES (1,'Thursday','09:00')")
        cur.execute("INSERT INTO pickup_schedules(zone_id,day,time) VALUES (2,'Tuesday','10:00')")
        cur.execute("INSERT INTO pickup_schedules(zone_id,day,time) VALUES (2,'Friday','10:00')")

    # Collector assignments are managed by admin (no default assignments).


    # Routes are generated dynamically when needed.

    conn.commit()
    conn.close()
    print("Migration complete. DB ready:", DB_PATH)

if __name__ == "__main__":
    main()
