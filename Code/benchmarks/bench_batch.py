"""
A/B BENCHMARK - legacy per-member rewards engine vs the batch pass
==================================================================
Builds a temporary SQLite database with N synthetic members (plus realistic
activity, guest, and facility data), then times and query-counts three paths:

  LEGACY    The pre-batch engine (`_legacy_engine_ref.py`, frozen from git
            HEAD): per-member calculate_engagement_score + the N^2 club-score
            loop inside update_member_rewards. This is what the old
            admin-members page ran for every member on every page load.

  NEW-READ  The batch read path EngagementEngine.view_all_rewards() - what
            the admin-members page (and CSV export) run today.

  NEW-WRITE The single batch write path EngagementEngine.recalculate_all()
            - what POST routes run after data-changing writes.

Both engines share the SAME scoring formula and data, so the numbers isolate
the architectural change (N*6 queries per member + N^2 club loop vs a
handful of grouped queries over one connection).

Run from the repo root:  python benchmarks/bench_batch.py
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time

N_MEMBERS = 200          # synthetic members to add (beyond the 3 seeded demos)
REPEATS_FAST = 5         # new paths are fast - average a few runs
LEGACY_SIZES = (50, N_MEMBERS)  # also show scaling on a smaller club

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BENCH_DIR)   # the Code/ package root
sys.path.insert(0, PROJECT_ROOT)

# config.py fails closed without a SECRET_KEY (VULN-001 fix). This benchmark
# only reads algorithm weights against a throwaway DB — a throwaway key is fine.
os.environ.setdefault("SECRET_KEY", "bench-batch-dev-key")

# --- 1. Point the app at a throwaway database and initialize it -------------
import config
config.Config.DATABASE = os.path.join(tempfile.gettempdir(), 'bench_batch_fairshare.db')
if os.path.exists(config.Config.DATABASE):
    os.remove(config.Config.DATABASE)

import database
from database import init_db
init_db()

# --- 2. Load BOTH engines: the frozen legacy reference and the current one ---
legacy_path = os.path.join(BENCH_DIR, '_legacy_engine_ref.py')
spec = importlib.util.spec_from_file_location('legacy_engine_ref', legacy_path)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)

import models as new_engine

# --- 3. Seed synthetic members with realistic mixed activity ----------------
def seed_members(n):
    conn = database.get_db()
    cur = conn.cursor()
    for i in range(n):
        username = "bench%d" % i
        cur.execute("SELECT u.id, m.id AS member_id FROM users u "
                    "LEFT JOIN members m ON m.user_id = u.id WHERE u.username = ?", (username,))
        row = cur.fetchone()
        if row and row['member_id'] is not None:
            continue  # already fully seeded
        if row:
            uid = row['id']  # orphan user (member was shrunk away) — reuse it
        else:
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (?, 'x', 'member')", (username,))
            uid = cur.lastrowid
        if i % 5 == 0:
            mtype = 'Premium'
        elif i % 11 == 0:
            mtype = 'VIP'
        else:
            mtype = 'Member'
        cur.execute(
            "INSERT INTO members (user_id, full_name, membership_type, email, phone, member_code) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uid, "Bench Member %d" % i, mtype, "bench%d@example.com" % i, "555-0000", "MBR-B%04d" % i))
        mid = cur.lastrowid

        # a visit, 1-3 purchases, occasionally a referral
        cur.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) "
                    "VALUES (?, 'visit', 'Club Visit', 0.0)", (mid,))
        for k in range(1 + (i % 3)):
            cur.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) "
                        "VALUES (?, 'purchase', 'Dining', ?)", (mid, round(25.0 + (i + k) * 7.5, 2)))
        if i % 4 == 0:
            cur.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value, guest_count) "
                        "VALUES (?, 'referral', 'Guest Referral', 0.0, 2)", (mid,))

        # a completed facility session for a third of members
        if i % 3 == 0:
            cur.execute("INSERT INTO facility_checkins "
                        "(member_id, facility_name, check_in_time, check_out_time, duration_minutes, status) "
                        "VALUES (?, 'Gym', datetime('now','-1 day'), datetime('now','-1 day'), ?, 'completed')",
                        (mid, 30 + (i % 90)))

        # a hosted guest with spending for a tenth of members
        if i % 10 == 0:
            cur.execute("INSERT INTO guest_ids (guest_code, guest_name, host_member_id) VALUES (?, ?, ?)",
                        ("GST-B%04d" % i, "Guest %d" % i, mid))
            gid = cur.lastrowid
            cur.execute("INSERT INTO guest_activities (guest_id, activity_type, service_name, transaction_value) "
                        "VALUES (?, 'purchase', 'Guest Dining', ?)", (gid, round(15.0 + i, 2)))

        # backdate join date for loyalty variation on a seventh of members
        if i % 7 == 0:
            cur.execute("UPDATE members SET join_date = datetime('now','-180 days') WHERE id = ?", (mid,))

    conn.commit()
    conn.close()


def member_ids():
    conn = database.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM members ORDER BY id")
    ids = [r['id'] for r in cur.fetchall()]
    conn.close()
    return ids


# --- 4. Query/connection counting harness - patches each module's get_db ----
def patch_get_db(module):
    """Replace module.get_db with a factory that counts statements and
    connections. sqlite3.Connection.cursor is read-only, so we subclass
    Connection and override cursor() to wrap execute()."""
    counts = {'queries': 0, 'connections': 0}

    class CountingCursor(sqlite3.Cursor):
        def execute(self, sql, *args):
            counts['queries'] += 1
            return super().execute(sql, *args)

    class CountingConnection(sqlite3.Connection):
        def cursor(self, factory=CountingCursor):
            return super().cursor(factory=factory)

    def counting_get_db():
        counts['connections'] += 1
        db_path = config.Config.DATABASE
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, factory=CountingConnection)
        conn.row_factory = sqlite3.Row
        # plain (uncounted) cursor for the per-connection PRAGMA
        conn.cursor(factory=sqlite3.Cursor).execute("PRAGMA foreign_keys = ON;")
        return conn

    module.get_db = counting_get_db
    return counts


legacy_counts = patch_get_db(legacy)
new_counts = patch_get_db(new_engine)

seed_members(N_MEMBERS)   # build the full synthetic club now

# --- 5. Timing helpers -------------------------------------------------------
def timed(fn):
    t0 = time.perf_counter()
    result = fn()
    return time.perf_counter() - t0, result


def run_legacy_page():
    """The old admin-members page: update_member_rewards for every member."""
    ids = member_ids()
    for mid in ids:
        legacy.EngagementEngine.update_member_rewards(mid)


def run_new_read():
    new_engine.EngagementEngine.view_all_rewards()


def run_new_write():
    new_engine.EngagementEngine.recalculate_all(force=True)  # explicit write path


# --- 6. Correctness spot-check: same formula, same numbers? -----------------
print("Spot-checking score equivalence (legacy vs batch)...")
ids = member_ids()
mismatches = 0
lq = 0
for mid in ids[:6]:
    legacy_counts['queries'] = legacy_counts['connections'] = 0
    old = legacy.EngagementEngine.calculate_engagement_score(mid)
    lq = legacy_counts['queries']
    new = new_engine.EngagementEngine.calculate_engagement_score(mid)
    if abs(old['engagement_score'] - new['engagement_score']) > 0.01:
        mismatches += 1
print("  checked 6 members, mismatches: %d, legacy per-member score = %d queries "
      "(settings + 6 aggregates)" % (mismatches, lq))
print()

# --- 7. Benchmark ------------------------------------------------------------
results = []

# LEGACY - at two club sizes to show the N^2 curve
for n in LEGACY_SIZES:
    seed_members(N_MEMBERS)  # idempotent: restore the full club, then shrink
    # shrink to n members: delete members beyond n (cascades activities etc.)
    conn = database.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM members ORDER BY id")
    all_ids = [r['id'] for r in cur.fetchall()]
    extra = all_ids[n:] if len(all_ids) > n else []
    for mid in extra:
        cur.execute("DELETE FROM members WHERE id = ?", (mid,))
    conn.commit()
    conn.close()

    legacy_counts['queries'] = legacy_counts['connections'] = 0
    t, _ = timed(run_legacy_page)
    m = len(member_ids())
    results.append(('LEGACY admin page (per-member, N^2 club loop)', n, t,
                    legacy_counts['queries'], legacy_counts['connections'], m))

# restore the full synthetic club for the new-engine runs
seed_members(N_MEMBERS)

conn = database.get_db()
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM members")
total_members = cur.fetchone()[0]
conn.close()

# NEW - read and write paths (averaged)
new_counts['queries'] = new_counts['connections'] = 0
t, _ = timed(lambda: [run_new_read() for _ in range(REPEATS_FAST)])
results.append(('NEW admin page (batch view_all_rewards)', N_MEMBERS,
                t / REPEATS_FAST, new_counts['queries'] // REPEATS_FAST,
                new_counts['connections'] // REPEATS_FAST, total_members))

new_counts['queries'] = new_counts['connections'] = 0
t, _ = timed(lambda: [run_new_write() for _ in range(REPEATS_FAST)])
results.append(('NEW write path (batch recalculate_all)', N_MEMBERS,
                t / REPEATS_FAST, new_counts['queries'] // REPEATS_FAST,
                new_counts['connections'] // REPEATS_FAST, total_members))

# --- 8. Report ---------------------------------------------------------------
print("=" * 88)
print("%-46s %7s %9s %9s %7s %9s" % ('Scenario', 'members', 'wall s', 'queries', 'conns', 'q/member'))
print("-" * 88)
for label, n, secs, q, c, m in results:
    print("%-46s %7d %9.3f %9d %7d %9d" % (label, m, secs, q, c, q // m))
print("-" * 88)

legacy50 = results[0]
legacy200 = results[1]
new_read = None
new_write = None
for r in results:
    if 'NEW admin page' in r[0]:
        new_read = r
    if 'NEW write path' in r[0]:
        new_write = r

print()
print("Scaling: legacy queries grow ~N^2:  %9d q @ %3d members  vs  %9d q @ %3d members"
      % (legacy50[3], legacy50[5], legacy200[3], legacy200[5]))
print("Speedup (200-member legacy page -> new read page): %.0fx wall clock, %dx fewer queries"
      % (legacy200[2] / new_read[2], legacy200[3] // new_read[3]))
print("Note: the legacy page ALSO wrote a rewards row per member on every load;")
print("the new read page writes nothing (writes now happen only in recalculate_all).")
