import sqlite3
import os
from werkzeug.security import generate_password_hash
from config import Config

def get_db():
    """Connect to SQLite database and set row factory."""
    db_path = Config.DATABASE
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initialize database tables and seed initial demo data."""
    conn = get_db()
    cursor = conn.cursor()

    # Create tables
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('member', 'admin')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            membership_type TEXT NOT NULL DEFAULT 'Standard',
            email TEXT NOT NULL,
            phone TEXT,
            member_code TEXT UNIQUE NOT NULL,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            activity_type TEXT NOT NULL CHECK(activity_type IN ('visit', 'purchase', 'referral', 'facility')),
            service_name TEXT NOT NULL,
            transaction_value REAL DEFAULT 0.0,
            guest_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS facility_checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            facility_name TEXT NOT NULL,
            check_in_time TIMESTAMP NOT NULL,
            check_out_time TIMESTAMP,
            duration_minutes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'completed')),
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS guest_ids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_code TEXT UNIQUE NOT NULL,
            guest_name TEXT NOT NULL,
            host_member_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (host_member_id) REFERENCES members (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS guest_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_id INTEGER NOT NULL,
            activity_type TEXT NOT NULL,
            service_name TEXT NOT NULL,
            transaction_value REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (guest_id) REFERENCES guest_ids (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reward_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_weight REAL NOT NULL DEFAULT 10.0,
            spending_weight REAL NOT NULL DEFAULT 0.5,
            referral_weight REAL NOT NULL DEFAULT 50.0,
            profit_sharing_pool REAL NOT NULL DEFAULT 10000.00,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            engagement_score REAL DEFAULT 0.0,
            discount_percentage REAL DEFAULT 0.0,
            earned_profit_share REAL DEFAULT 0.0,
            redemption_code TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'redeemed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
        );
    ''')

    # Seed Default Reward Settings if empty
    cursor.execute("SELECT COUNT(*) FROM reward_settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO reward_settings (visit_weight, spending_weight, referral_weight, profit_sharing_pool)
            VALUES (?, ?, ?, ?)
        ''', (Config.DEFAULT_VISIT_WEIGHT, Config.DEFAULT_SPENDING_WEIGHT, Config.DEFAULT_REFERRAL_WEIGHT, Config.DEFAULT_PROFIT_POOL))

    # Seed Demo Admin User if empty
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        admin_pass = generate_password_hash("admin123")
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ("admin", admin_pass, "admin"))

    # Seed Demo Member Users if empty
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'member'")
    if cursor.fetchone()[0] == 0:
        demo_members = [
            ("alice", "password123", "Alice Johnson", "VIP Gold", "alice@example.com", "555-0101", "MBR-1001"),
            ("bob", "password123", "Bob Smith", "Standard", "bob@example.com", "555-0102", "MBR-1002"),
            ("charlie", "password123", "Charlie Davis", "Platinum", "charlie@example.com", "555-0103", "MBR-1003")
        ]
        
        for username, plain_pw, full_name, mtype, email, phone, mcode in demo_members:
            pw_hash = generate_password_hash(plain_pw)
            cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", (username, pw_hash, "member"))
            user_id = cursor.lastrowid
            cursor.execute('''
                INSERT INTO members (user_id, full_name, membership_type, email, phone, member_code)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, full_name, mtype, email, phone, mcode))
            member_id = cursor.lastrowid

            # Seed sample activity data
            if username == "alice":
                cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) VALUES (?, 'visit', 'Club House Visit', 0.0)", (member_id,))
                cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) VALUES (?, 'purchase', 'Club Dining Restaurant', 180.50)", (member_id,))
                cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value, guest_count) VALUES (?, 'referral', 'Guest Referral - VIP Lounge', 0.0, 2)", (member_id,))
            elif username == "bob":
                cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) VALUES (?, 'visit', 'Fitness Gym Visit', 0.0)", (member_id,))
                cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) VALUES (?, 'purchase', 'Pro Shop Equipment', 45.00)", (member_id,))
            elif username == "charlie":
                cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) VALUES (?, 'visit', 'Tennis Court Session', 0.0)", (member_id,))
                cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) VALUES (?, 'purchase', 'Bistro & Grill', 320.00)", (member_id,))
                cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value, guest_count) VALUES (?, 'referral', 'Guest Referral - Golf Tournament', 0.0, 3)", (member_id,))

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
