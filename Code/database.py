"""
================================================================================
 DATABASE LAYER (Persistence) — IB HL CS: Databases & SQL
================================================================================
 This module implements the *persistence layer* of the FairShare system.

 KEY IB HL CS CONCEPTS DEMONSTRATED:
  * Relational database design: data is decomposed into normalised tables
    (users, members, activities, rewards, ...) so that no fact is stored
    twice (eliminates redundancy / update anomalies).
  * Referential integrity: FOREIGN KEY constraints + `ON DELETE CASCADE`
    guarantee that child records (e.g. a member's activities) can never
    reference a parent (member) that no longer exists.
  * Data integrity rules at the schema level: UNIQUE, NOT NULL and CHECK
    constraints enforce validity BEFORE any application code runs.
  * Structured Query Language (SQL): DDL (CREATE/ALTER TABLE) and DML
    (INSERT/UPDATE) are executed through parameterised statements.
  * SQL triggers (event-driven automation): the dirty-flag triggers at the
    bottom of init_db() automatically mark the rewards cache as stale on
    every write — the application never has to remember to do it.
  * Migrations: ALTER TABLE ... ADD COLUMN statements let existing databases
    be upgraded in place when the schema evolves between versions.

 WHY SQLite?  A single-file, serverless, transactional relational DBMS —
 perfect for an IA prototype because it needs no separate server process
 and supports the full ACID properties (Atomicity, Consistency, Isolation,
 Durability) via transactions.
"""
import sqlite3
import os
import secrets
from werkzeug.security import generate_password_hash
from config import Config

def get_db():
    """Connect to the database and set row factory.

    Two backends, chosen by environment:

    * DEFAULT (no TURSO_URL): a local SQLite file at Config.DATABASE.
    * HOSTED (TURSO_URL set): a Turso / libSQL database — SQLite-compatible
      and persistent on serverless platforms (Vercel). The connection is
      wrapped in a sqlite3-compatible adapter (see _TursoConnection below)
      so every caller below uses the identical cursor API.

    IB HL CS NOTES:
    * This is a *factory function* — every caller gets a fresh connection,
      which isolates transactions between requests (a form of encapsulation
      at the connection level).
    * `sqlite3.Row` row factory makes query results accessible BOTH by index
      (row[0]) and by column name (row['member_id']) — like a dictionary.
      This improves code readability and maintainability over raw tuples.
    * `PRAGMA foreign_keys = ON` is essential: SQLite disables foreign-key
      enforcement by default, so without this line the ON DELETE CASCADE
      rules defined in the schema would be silently ignored. (libSQL, the
      engine behind Turso, enforces foreign keys by default, so the hosted
      path skips the pragma.)
    """
    turso_url = os.environ.get('TURSO_URL')
    if turso_url:
        return _TursoConnection(turso_url, os.environ.get('TURSO_AUTH_TOKEN'))

    db_path = Config.DATABASE
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ---------------------------------------------------------------------------
# HOSTED SQLITE ADAPTER (Turso / libSQL) — optional persistent storage
# ---------------------------------------------------------------------------
# Local SQLite stores data in a file, which a serverless filesystem (Vercel)
# cannot keep: it is read-only outside /tmp and /tmp resets per instance, so
# logins, points and receipts would be lost on every cold start. To make the
# data survive, the app can instead talk to a HOSTED SQLite-compatible
# database. Turso (https://turso.tech) runs libSQL — a SQLite fork — so all
# of this project's SQL (CREATE TRIGGER, date('now'), strftime, PRAGMA
# table_info migrations, AUTOINCREMENT, BEGIN IMMEDIATE transactions) works
# unchanged.
#
# The classes below are a thin sqlite3-compatible shim over the official
# `libsql-client` Python package. They implement exactly the connection /
# cursor surface the rest of the codebase uses — cursor(), fetchone(),
# fetchall(), lastrowid, rowcount, executescript(), executemany(),
# commit(), rollback(), close(), and rows addressable by index or column
# name — so models.py and main.py need no changes at all.
#
# Enable it by setting TURSO_URL (the libsql://... connection URL from the
# Turso dashboard — that scheme maps to WebSockets/Hrana, which supports
# transactions; the https:// scheme does NOT) and optionally TURSO_AUTH_TOKEN
# (a bearer token, required for remote databases). Without TURSO_URL the app
# keeps using the local data/fairshare.db file exactly as before.
#
# IB HL CS: this is *abstraction / separation of concerns* — the persistence
# backend is hidden behind one consistent interface, so swapping storage
# changes one factory function instead of every query.


def _split_statements(sql):
    """Split a SQL script into individual statements on semicolons that
    appear OUTSIDE quoted strings. sqlite3.executescript() runs many
    statements at once, but the libsql client executes one statement per
    call, so the adapter splits first (safe for this schema's DDL, which
    contains no semicolons inside string literals)."""
    statements = []
    current = []
    quote = None
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if quote:
            current.append(ch)
            if ch == quote and (i == 0 or sql[i - 1] != '\\'):
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            current.append(ch)
        elif ch == ';':
            statements.append(''.join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    statements.append(''.join(current))
    return [s for s in statements if s.strip()]


class _TursoRow:
    """A result row that behaves like sqlite3.Row: addressable by column
    number (row[0]) or column name (row['member_id']), iterable, and
    convertible with dict(row) — which the admin analytics and guest-report
    JSON serialisation rely on."""
    __slots__ = ('_cols', '_vals', '_map')

    def __init__(self, columns, values):
        self._cols = list(columns)
        self._vals = list(values)
        self._map = dict(zip(self._cols, self._vals))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._map[key]

    def keys(self):
        return self._cols

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __contains__(self, key):
        return key in self._map

    def asdict(self):
        return dict(zip(self._cols, self._vals))


class _TursoCursor:
    """sqlite3-style cursor over a shared libsql client. Each execute()
    stores the ResultSet; fetchone()/fetchall() consume it lazily, exactly
    like a sqlite3 cursor."""

    def __init__(self, connection):
        self._conn = connection
        self._rows = []
        self._pos = 0
        self.lastrowid = None
        self.rowcount = -1

    def execute(self, sql, params=()):
        self._conn._ensure_open()
        statement = sql.strip()
        upper = statement.upper()
        # models.py opens write-locked transactions with
        # conn.execute("BEGIN IMMEDIATE") and closes them with commit() /
        # rollback(). Over the Hrana protocol a transaction is a STREAM-STATE
        # change, not SQL text: executing the literal string "BEGIN IMMEDIATE"
        # is silently ignored by the server ("cannot commit - no transaction
        # is active"). Route transaction control through the client's
        # transaction() API instead, and run later statements on that stream.
        if upper.startswith('BEGIN'):
            self._conn._open_txn()
            return self
        if upper.startswith('COMMIT'):
            self._conn.commit()
            return self
        if upper.startswith('ROLLBACK'):
            self._conn.rollback()
            return self

        # A regular statement runs inside the open transaction if there is
        # one, otherwise directly on the client connection.
        client = self._conn._txn if self._conn._txn is not None else self._conn._client
        result = client.execute(statement, params)
        self.lastrowid = result.last_insert_rowid
        self.rowcount = result.rows_affected
        columns = result.columns
        if columns:
            self._rows = [_TursoRow(columns, list(values)) for values in result.rows]
        else:
            self._rows = []
        self._pos = 0
        return self

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def executescript(self, sql):
        for statement in _split_statements(sql):
            self.execute(statement)
        return self

    def executemany(self, sql, seq_of_params):
        for params in seq_of_params:
            self.execute(sql, params)
        return self

    def close(self):
        pass


class _TursoConnection:
    """sqlite3-compatible connection backed by a libSQL (Turso) database.
    The real client is created lazily so the app still boots on machines
    where libsql-client is not installed (as long as TURSO_URL is unset)."""

    def __init__(self, url, auth_token=None):
        try:
            from libsql_client import create_client_sync
        except ImportError as exc:
            raise RuntimeError(
                "TURSO_URL is set but the 'libsql-client' package is not "
                "installed. Install it with: pip install libsql-client"
            ) from exc
        self._client = create_client_sync(url, auth_token=auth_token)
        self._txn = None  # active Hrana TransactionSync, or None
        self._closed = False
        self.row_factory = None  # rows are already index/name-addressable

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("database connection is closed")

    def _open_txn(self):
        """Open a real Hrana stream transaction (see _TursoCursor.execute)."""
        if self._txn is None:
            self._txn = self._client.transaction()

    def cursor(self):
        return _TursoCursor(self)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return self.cursor().executemany(sql, seq_of_params)

    def executescript(self, sql):
        return self.cursor().executescript(sql)

    def commit(self):
        if self._txn is not None:
            txn, self._txn = self._txn, None
            txn.commit()

    def rollback(self):
        if self._txn is not None:
            txn, self._txn = self._txn, None
            try:
                txn.rollback()
            except Exception:
                # The transaction may already be closed (e.g. a statement or
                # commit failed); discarding it is the rollback here.
                pass

    def close(self):
        if not self._closed:
            if self._txn is not None:
                try:
                    self._txn.rollback()
                except Exception:
                    pass
                self._txn = None
            self._client.close()
            self._closed = True

    # Context-manager support mirrors sqlite3.Connection: commit on clean
    # exit, rollback on error.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

def init_db():
    """Initialize database tables and seed initial demo data."""
    conn = get_db()
    cursor = conn.cursor()

    # Create tables
    # ------------------------------------------------------------------
    # SCHEMA DESIGN — IB HL CS: Normalisation & Entity-Relationship model
    # ------------------------------------------------------------------
    # The database is decomposed into separate *entities* (tables) linked by
    # primary keys (id) and foreign keys (e.g. members.user_id). This is the
    # relational model: each table stores one kind of fact, eliminating
    # redundancy (e.g. a member's name is stored once in `members`, NOT in
    # every activity row). CHECK constraints encode *domain rules* directly
    # in the schema, e.g. activity_type must be one of the four allowed
    # values — this is validation at the deepest layer of the system.
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
            membership_type TEXT NOT NULL DEFAULT 'Member',
            email TEXT NOT NULL,
            phone TEXT,
            member_code TEXT UNIQUE NOT NULL,
            yearly_fee REAL NOT NULL DEFAULT 1200.00,
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
            guest_id INTEGER,
            facility_name TEXT NOT NULL,
            check_in_time TIMESTAMP NOT NULL,
            check_out_time TIMESTAMP,
            duration_minutes INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'completed')),
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE,
            FOREIGN KEY (guest_id) REFERENCES guest_ids (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS guest_ids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_code TEXT UNIQUE NOT NULL,
            guest_name TEXT NOT NULL,
            host_member_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'revoked')),
            revoked_at TIMESTAMP,
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

        CREATE TABLE IF NOT EXISTS guest_pass_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guest_id INTEGER UNIQUE NOT NULL,
            host_member_id INTEGER NOT NULL,
            guest_code TEXT NOT NULL,
            guest_name TEXT NOT NULL,
            issued_at TIMESTAMP NOT NULL,
            revoked_at TIMESTAMP NOT NULL,
            activity_count INTEGER NOT NULL DEFAULT 0,
            total_spending REAL NOT NULL DEFAULT 0.0,
            total_facility_minutes INTEGER NOT NULL DEFAULT 0,
            activity_snapshot TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY (guest_id) REFERENCES guest_ids (id) ON DELETE RESTRICT,
            FOREIGN KEY (host_member_id) REFERENCES members (id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS reward_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_weight REAL NOT NULL DEFAULT 10.0,
            spending_weight REAL NOT NULL DEFAULT 0.5,
            referral_weight REAL NOT NULL DEFAULT 50.0,
            facility_weight REAL NOT NULL DEFAULT 0.2,
            loyalty_weight REAL NOT NULL DEFAULT 5.0,
            premium_multiplier REAL NOT NULL DEFAULT 1.0,
            vip_multiplier REAL NOT NULL DEFAULT 1.0,
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

        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_code TEXT UNIQUE NOT NULL,
            service_name TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'unscanned' CHECK(status IN ('unscanned', 'scanned')),
            scanned_by_member INTEGER,
            scanned_by_guest INTEGER,
            scanned_at TIMESTAMP,
            issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (scanned_by_member) REFERENCES members (id) ON DELETE SET NULL,
            FOREIGN KEY (scanned_by_guest) REFERENCES guest_ids (id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'Facility',
            cost_points REAL NOT NULL DEFAULT 0.0,
            value_amount REAL NOT NULL DEFAULT 0.0,
            facility_name TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS member_coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            coupon_id INTEGER NOT NULL,
            coupon_code TEXT UNIQUE NOT NULL,
            points_spent REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'used')),
            claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_at TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE,
            FOREIGN KEY (coupon_id) REFERENCES coupons (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS point_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            points_delta REAL NOT NULL,
            reason TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            username TEXT PRIMARY KEY,
            fail_count INTEGER NOT NULL DEFAULT 0,
            locked_until REAL
        );
    ''')

    # ------------------------------------------------------------------
    # MIGRATIONS — IB HL CS: Schema Evolution
    # ------------------------------------------------------------------
    # A migration upgrades an EXISTING database (created by an older version
    # of the code) without destroying its data. PRAGMA table_info returns the
    # current columns; if a new column is missing, ALTER TABLE adds it. This
    # makes init_db() *idempotent*: safe to run on every app launch.
    # Migration: add guest facility tracking column to facility_checkins (existing databases)
    cursor.execute("PRAGMA table_info(facility_checkins)")
    checkin_cols = [row[1] for row in cursor.fetchall()]
    if 'guest_id' not in checkin_cols:
        cursor.execute("ALTER TABLE facility_checkins ADD COLUMN guest_id INTEGER REFERENCES guest_ids(id) ON DELETE CASCADE")

    # Migration: add revocation state to existing guest passes
    cursor.execute("PRAGMA table_info(guest_ids)")
    guest_cols = [row[1] for row in cursor.fetchall()]
    if 'status' not in guest_cols:
        cursor.execute("ALTER TABLE guest_ids ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if 'revoked_at' not in guest_cols:
        cursor.execute("ALTER TABLE guest_ids ADD COLUMN revoked_at TIMESTAMP")

    # Migration: add facility/loyalty/tier scoring columns to reward_settings
    cursor.execute("PRAGMA table_info(reward_settings)")
    settings_cols = [row[1] for row in cursor.fetchall()]
    if 'facility_weight' not in settings_cols:
        cursor.execute("ALTER TABLE reward_settings ADD COLUMN facility_weight REAL NOT NULL DEFAULT 0.2")
    if 'loyalty_weight' not in settings_cols:
        cursor.execute("ALTER TABLE reward_settings ADD COLUMN loyalty_weight REAL NOT NULL DEFAULT 5.0")
    if 'premium_multiplier' not in settings_cols:
        cursor.execute("ALTER TABLE reward_settings ADD COLUMN premium_multiplier REAL NOT NULL DEFAULT 1.0")
    if 'vip_multiplier' not in settings_cols:
        cursor.execute("ALTER TABLE reward_settings ADD COLUMN vip_multiplier REAL NOT NULL DEFAULT 1.0")
    if 'points_value_dollars' not in settings_cols:
        cursor.execute("ALTER TABLE reward_settings ADD COLUMN points_value_dollars REAL NOT NULL DEFAULT 0.50")

    # Migration: add yearly membership fee columns to members (existing databases)
    cursor.execute("PRAGMA table_info(members)")
    member_cols = [row[1] for row in cursor.fetchall()]
    if 'yearly_fee' not in member_cols:
        cursor.execute("ALTER TABLE members ADD COLUMN yearly_fee REAL NOT NULL DEFAULT 1200.00")
    if 'fee_points_applied' not in member_cols:
        cursor.execute("ALTER TABLE members ADD COLUMN fee_points_applied REAL NOT NULL DEFAULT 0.0")
    if 'fee_paid' not in member_cols:
        cursor.execute("ALTER TABLE members ADD COLUMN fee_paid INTEGER NOT NULL DEFAULT 0")

    # ------------------------------------------------------------------
    # SEEDING — IB HL CS: Pre-populated Test Data
    # ------------------------------------------------------------------
    # A fresh install has no rows, so we seed demo accounts and activity so
    # the application is immediately usable and testable. Seeding is guarded
    # by COUNT(*) checks so it only runs on a genuinely empty database.
    # Passwords are stored as *hashes* (one-way functions, see werkzeug's
    # generate_password_hash) — never plain text — satisfying the security
    # requirement of the success criteria.

    # Seed Default Reward Settings if empty
    cursor.execute("SELECT COUNT(*) FROM reward_settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO reward_settings (
                visit_weight, spending_weight, referral_weight, facility_weight,
                loyalty_weight, premium_multiplier, vip_multiplier, profit_sharing_pool,
                points_value_dollars
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            Config.DEFAULT_VISIT_WEIGHT, Config.DEFAULT_SPENDING_WEIGHT,
            Config.DEFAULT_REFERRAL_WEIGHT, Config.DEFAULT_FACILITY_WEIGHT,
            Config.DEFAULT_LOYALTY_WEIGHT,
            1.0,
            1.0,
            Config.DEFAULT_PROFIT_POOL,
            Config.DEFAULT_POINTS_VALUE_DOLLARS
        ))

    # Seed the initial Admin User if empty.
    # SECURITY (VULN-001 fix): the admin password is NEVER a hardcoded
    # default. It comes from the ADMIN_PASSWORD environment variable (set by
    # the operator at deploy time); if that is not provided, a strong random
    # password is generated and printed ONCE to the startup log (readable
    # from the operator's console / server logs). Only the salted hash is
    # stored in the database.
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        admin_pass = os.environ.get('ADMIN_PASSWORD') or secrets.token_urlsafe(12)
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("admin", generate_password_hash(admin_pass), "admin")
        )
        print(f"[FairShare] Created the initial admin account: username 'admin', "
              f"password '{admin_pass}' (set ADMIN_PASSWORD to choose your own).", flush=True)

    # Seed Demo Member Users if empty — OPT-IN ONLY (SEED_DEMO_DATA=1).
    # SECURITY (VULN-001 fix): the demo members' passwords are documented in
    # the README, so a public deployment must never contain them by default.
    # The launcher scripts (run.sh / run.bat) and the test suite enable
    # SEED_DEMO_DATA for local development; deployments leave it unset and
    # create real members from the admin panel.
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'member'")
    if cursor.fetchone()[0] == 0 and os.environ.get('SEED_DEMO_DATA') == '1':
        demo_members = [
            ("alice", "password123", "Alice Johnson", "Member", "alice@example.com", "555-0101", "MBR-1001"),
            ("bob", "password123", "Bob Smith", "Member", "bob@example.com", "555-0102", "MBR-1002"),
            ("charlie", "password123", "Charlie Davis", "Member", "charlie@example.com", "555-0103", "MBR-1003"),
            ("diana", "password123", "Diana Patel", "Member", "diana@example.com", "555-0104", "MBR-1004")
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
            elif username == "diana":
                # Second rich demo profile: a full history so reviewers can
                # explore visits, spending, referrals, facility minutes,
                # guest credit and loyalty points on another member.
                cursor.execute("UPDATE members SET join_date = ? WHERE id = ?", ("2026-01-15 09:00:00", member_id))
                demo_activities = [
                    ("visit", "Club House Visit", 0.0, 0, "2026-02-03 10:12:00"),
                    ("visit", "Fitness Gym Visit", 0.0, 0, "2026-05-18 07:45:00"),
                    ("visit", "Tennis Court Session", 0.0, 0, "2026-07-22 16:30:00"),
                    ("purchase", "Bistro & Lounge", 250.00, 0, "2026-04-11 20:05:00"),
                    ("purchase", "Pro Shop Equipment", 180.00, 0, "2026-06-09 15:40:00"),
                    ("purchase", "Spa & Wellness Retreat", 95.00, 0, "2026-07-25 11:20:00"),
                    ("referral", "Guest Referral - Tennis Day", 0.0, 2, "2026-03-14 13:00:00"),
                ]
                for atype, svc, val, guests, created in demo_activities:
                    cursor.execute('''
                        INSERT INTO activities (member_id, activity_type, service_name, transaction_value, guest_count, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (member_id, atype, svc, val, guests, created))
                # Completed facility sessions — these feed the facility-minutes stat
                demo_checkins = [
                    ("Club Fitness & Gym", "2026-07-10 08:00:00", "2026-07-10 08:45:00", 45),
                    ("Swimming Pool & Spa", "2026-07-18 14:00:00", "2026-07-18 15:00:00", 60),
                    ("Pro Golf Course", "2026-07-27 09:00:00", "2026-07-27 11:00:00", 120),
                ]
                for fac, cin, cout, mins in demo_checkins:
                    cursor.execute('''
                        INSERT INTO facility_checkins (member_id, facility_name, check_in_time, check_out_time, duration_minutes, status)
                        VALUES (?, ?, ?, ?, ?, 'completed')
                    ''', (member_id, fac, cin, cout, mins))
                # Guest day-pass + spending, all credited to Diana as host
                cursor.execute('''
                    INSERT INTO guest_ids (guest_code, guest_name, host_member_id, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (f"GST-{secrets.token_hex(8).upper()}", "Nina Patel", member_id, "2026-07-29 10:00:00"))
                guest_id = cursor.lastrowid
                cursor.execute('''
                    INSERT INTO guest_activities (guest_id, activity_type, service_name, transaction_value, created_at)
                    VALUES (?, 'purchase', 'Bistro & Lounge - Guest', 150.00, '2026-07-29 19:30:00')
                ''', (guest_id,))

    # Seed Demo Expense Receipts (QR-scannable vouchers) if empty
    cursor.execute("SELECT COUNT(*) FROM receipts")
    if cursor.fetchone()[0] == 0:
        demo_receipts = [
            ("Club Restaurant Dining", 42.75),
            ("Pro Shop Equipment", 18.99),
            ("Spa & Wellness Retreat", 95.00),
            ("Bistro & Lounge", 12.50),
        ]
        for svc, amt in demo_receipts:
            rcode = f"RCPT-{secrets.token_hex(8).upper()}"
            cursor.execute("INSERT INTO receipts (receipt_code, service_name, amount) VALUES (?, ?, ?)", (rcode, svc, amt))

    # Seed Coupon Marketplace catalog if empty
    cursor.execute("SELECT COUNT(*) FROM coupons")
    if cursor.fetchone()[0] == 0:
        demo_coupons = [
            ("Gym Day Pass", "Full-day access to the Club Fitness & Gym. Scan your coupon QR at the gym desk to check in.", "Facility", 40.0, 10.00, "Club Fitness & Gym"),
            ("Tennis Court Hour", "One hour of reserved play on the Tennis & Squash Courts for you and a guest.", "Facility", 60.0, 18.00, "Tennis & Squash Courts"),
            ("Pool & Spa Session", "A relaxing afternoon session at the Swimming Pool & Spa, including towel service.", "Facility", 80.0, 25.00, "Swimming Pool & Spa"),
            ("Pro Golf Round", "One 18-hole round on the Pro Golf Course with cart included.", "Facility", 150.0, 45.00, "Pro Golf Course"),
            ("$15 Bistro Voucher", "Spend $15 toward anything on the Bistro & Lounge menu.", "Dining", 50.0, 15.00, None),
            ("10% Pro Shop Discount", "Save 10% on a single purchase at the Pro Shop, up to $25 in savings.", "Pro Shop", 90.0, 25.00, None),
            ("Free Guest Pass", "Generate a free guest day-pass for a visitor - all their activity still credits your points.", "Membership", 70.0, 0.00, None),
            ("Priority Booking Access", "Skip the queue for weekend facility bookings for one month.", "Events", 120.0, 0.00, None),
        ]
        for name, desc, cat, cost, val, facility in demo_coupons:
            cursor.execute(
                "INSERT INTO coupons (name, description, category, cost_points, value_amount, facility_name) VALUES (?, ?, ?, ?, ?, ?)",
                (name, desc, cat, cost, val, facility)
            )

    # Seed Diana's claimed marketplace coupons AFTER the catalog exists (so the
    # coupon ids are known) plus the matching point-ledger entries — her
    # spendable balance already reflects these claims.
    cursor.execute("SELECT id FROM members WHERE member_code = 'MBR-1004'")
    diana_row = cursor.fetchone()
    if diana_row:
        diana_id = diana_row['id']
        cursor.execute("SELECT id, name, cost_points FROM coupons WHERE name IN ('Gym Day Pass', 'Tennis Court Hour') ORDER BY id")
        for coupon in cursor.fetchall():
            ccode = f"CPN-{secrets.token_hex(8).upper()}"
            cursor.execute('''
                INSERT INTO member_coupons (member_id, coupon_id, coupon_code, points_spent, status, claimed_at)
                VALUES (?, ?, ?, ?, 'active', ?)
            ''', (diana_id, coupon['id'], ccode, coupon['cost_points'], "2026-08-01 09:10:00"))
            cursor.execute('''
                INSERT INTO point_transactions (member_id, points_delta, reason, created_at)
                VALUES (?, ?, ?, ?)
            ''', (diana_id, -coupon['cost_points'], f"Claimed coupon: {coupon['name']}", "2026-08-01 09:10:00"))

    # ------------------------------------------------------------------
    # DIRTY-FLAG + TRIGGERS — IB HL CS: Event-driven processing & caching
    # ------------------------------------------------------------------
    # This is the clever part that makes the batch rewards engine efficient.
    #
    # PROBLEM: recomputing every member's engagement score after every write
    # is expensive. But doing it lazily requires knowing *when* data changed.
    #
    # SOLUTION: a singleton table `rewards_recompute` stores one flag. SQLite
    # TRIGGERS fire automatically AFTER any INSERT/UPDATE/DELETE on the seven
    # scoring tables and set the flag. The first read after a change sees
    # the flag and triggers one batch recompute; subsequent reads are pure
    # reads (O(1) flag check). This is *event-driven architecture*: the
    # database notifies the application of changes instead of the app
    # polling or guessing.
    #
    # IB note: triggers are a form of procedural extension to SQL — they
    # move business logic into the DBMS itself.

    # Singleton row (id=1) that records whether any scoring-relevant data
    # changed since the last batch rewards recompute. SQLite triggers set it
    # on every write to the scoring tables; EngagementEngine's lazy batch
    # recompute clears it after materializing fresh reward rows. This means
    # no route ever needs to remember to call recalculate_all() — a write is
    # automatically detected and the recompute runs on the next rewards read.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rewards_recompute (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            pending INTEGER NOT NULL DEFAULT 0
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO rewards_recompute (id, pending) VALUES (1, 0)")

    # Triggers are created AFTER seeding so a fresh install starts with a clean
    # flag (read paths stay read-only until the first real data change). DROP +
    # CREATE keeps this idempotent so existing databases pick up the triggers
    # on next startup. `rewards` is included so the redeem flow (which flips an
    # active row to 'redeemed') also invalidates the cache.
    #
    # Loop + string formatting generate one trigger per (table, verb) pair —
    # 7 tables x 3 verbs = 21 triggers. This is metaprogramming at the schema
    # level: writing repetitive SQL by hand would be error-prone, so we let a
    # loop (a programming construct) generate it deterministically.
    for table in ('activities', 'guest_activities', 'facility_checkins',
                  'members', 'reward_settings', 'point_transactions', 'rewards'):
        for verb in ('INSERT', 'UPDATE', 'DELETE'):
            cursor.execute(f"DROP TRIGGER IF EXISTS trg_{table}_{verb.lower()}_dirty")
            cursor.execute(
                f"CREATE TRIGGER trg_{table}_{verb.lower()}_dirty AFTER {verb} ON {table} "
                "BEGIN UPDATE rewards_recompute SET pending = 1 WHERE id = 1; END"
            )

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
