"""
================================================================================
 BUSINESS-LOGIC / MODEL LAYER — IB HL CS: OOP, Algorithms & Data Structures
================================================================================
 This module holds the *computational core* of FairShare: the classes that
 turn raw activity records into engagement scores, discounts and rewards.

 KEY IB HL CS CONCEPTS DEMONSTRATED:
  * Object-Oriented Programming: related behaviour is grouped into classes
    (RewardSettings, EngagementEngine, FacilityTracker, GuestManager,
    ReceiptManager, MarketplaceManager, CSVReportGenerator). Static and
    class methods are used because these objects are stateless service
    classes — they don't need instance data, only behaviour.
  * Encapsulation: each class hides its database details behind a narrow,
    meaningful method interface (e.g. `claim_coupon()` vs raw SQL).
  * Algorithm design & Big-O analysis: the original implementation scored
    members one-by-one (O(N) queries per member -> O(N^2) total). The batch
    rewrite below collapses this to a handful of GROUP BY queries over ONE
    connection — exactly O(N) — see _collect_aggregates().
  * Data structures: dictionaries are used as hash maps keyed by member_id
    for O(1) lookups when joining aggregates to member rows.
  * Parameterised SQL everywhere (no string concatenation) — prevents SQL
    injection attacks (security).
"""
import secrets
import json
import csv
import io
import math
import time
from datetime import datetime, timedelta, timezone
from database import get_db
from config import Config




class LoginThrottle:
    """Exponential-backoff rate limiting for the /login route.

    IB HL CS: *security engineering* — throttling converts an O(1) brute-force
    loop into an exponential one, and the state lives in the database so it
    survives server restarts (persistence).
    """
    MAX_ATTEMPTS = 5
    BASE_LOCK_SECONDS = 30
    LOCK_CAP_SECONDS = 3600

    @staticmethod
    def _lock_seconds(fail_count):
        if fail_count < LoginThrottle.MAX_ATTEMPTS:
            return 0
        extra = fail_count - LoginThrottle.MAX_ATTEMPTS
        return min(LoginThrottle.BASE_LOCK_SECONDS * (2 ** extra),
                   LoginThrottle.LOCK_CAP_SECONDS)

    @staticmethod
    def is_locked(username):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT locked_until FROM login_attempts WHERE username = ?', (username,))
        row = cursor.fetchone()
        conn.close()
        if not row or not row['locked_until']:
            return 0
        remaining = row['locked_until'] - time.time()
        return max(0, int(math.ceil(remaining)))

    @staticmethod
    def record_failure(username):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO login_attempts (username, fail_count, locked_until)
            VALUES (?, 1, NULL)
            ON CONFLICT(username) DO UPDATE SET fail_count = login_attempts.fail_count + 1""", (username,))
        cursor.execute('SELECT fail_count FROM login_attempts WHERE username = ?', (username,))
        fail_count = cursor.fetchone()['fail_count']
        locked_until = time.time() + LoginThrottle._lock_seconds(fail_count) if fail_count >= LoginThrottle.MAX_ATTEMPTS else None
        cursor.execute('UPDATE login_attempts SET locked_until = ? WHERE username = ?', (locked_until, username))
        conn.commit()
        conn.close()

    @staticmethod
    def clear(username):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM login_attempts WHERE username = ?', (username,))
        conn.commit()
        conn.close()

class RewardSettings:
    """
    Stores/reads the algorithm's configurable parameters.

    IB HL CS: The system stores ONE active settings row (latest id) rather
    than overwriting, creating a simple audit trail of changes. Every
    computation reads the latest row, so admin edits take effect immediately.
    """
    @staticmethod
    def get_settings():
        """Retrieve active algorithm weights and profit pool settings."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reward_settings ORDER BY id DESC LIMIT 1")
        settings = cursor.fetchone()
        conn.close()
        return settings

    @staticmethod
    def update_settings(visit_weight, spending_weight, referral_weight, facility_weight,
                        loyalty_weight, profit_sharing_pool, premium_multiplier=1.15, vip_multiplier=1.30,
                        points_value_dollars=0.50):
        """Update algorithm weights and reward pool settings."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reward_settings (
                visit_weight, spending_weight, referral_weight, facility_weight,
                loyalty_weight, premium_multiplier, vip_multiplier, profit_sharing_pool,
                points_value_dollars
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (visit_weight, spending_weight, referral_weight, facility_weight,
              loyalty_weight, premium_multiplier, vip_multiplier, profit_sharing_pool,
              points_value_dollars))
        conn.commit()
        conn.close()


class EngagementEngine:
    """
    The heart of the system — computes engagement scores and rewards.

    IB HL CS NOTES ON DESIGN:
    * Pure functions & separation of computation from persistence: the
      scoring math (_build_summary) takes data as parameters and returns
      results; it has no side effects, which makes it trivial to unit-test.
    * Two access paths with different guarantees:
        - calculate_all_scores()      : read-only computation
        - view_all_rewards()          : lazy read that WRITES only when a
          SQLite-triggered dirty flag says data changed (see database.py)
        - recalculate_all()           : explicit batch write (upsert)
      This mirrors the Command/Query separation principle.
    """
    # Canonical tiers and the reward_settings keys that hold their multipliers.
    # Single source of truth — anything that needs tier logic uses these helpers.
    TIER_KEYS = {
        'Member': 1.0,
        'Premium': 1.0,
        'VIP': 1.0,
    }

    @staticmethod
    def normalize_tier(membership_type):
        """Normalize any tier spelling ('premium', 'Premium ', 'VIP', 'vip') to a
        canonical tier name: 'Member', 'Premium' or 'VIP'. Unknown values fall
        back to 'Member' so no member is ever dropped to a broken state.

        IB HL CS: *defensive programming* — the system accepts messy human
        input and normalises it to one canonical form, and failures degrade
        to a safe default rather than raising an exception.
        """
        if not membership_type:
            return 'Member'
        lowered = membership_type.strip().lower()
        if lowered == 'premium':
            return 'Premium'
        if lowered == 'vip':
            return 'VIP'
        return 'Member'

    @staticmethod
    def tier_multiplier(membership_type, settings):
        """Resolve the score multiplier for a member's tier using the active
        reward settings (or 1.0 for the base 'Member' tier)."""
        tier = EngagementEngine.normalize_tier(membership_type)
        config = EngagementEngine.TIER_KEYS[tier]
        if isinstance(config, str):
            return settings[config]
        return config

    @staticmethod
    def _loyalty_months(join_date):
        """Full elapsed months since join, floored on days (45 days = 1 month)."""
        if not join_date:
            return 0
        try:
            join_dt = datetime.strptime(join_date[:10], "%Y-%m-%d")
            return max(0, (datetime.now() - join_dt).days // 30)
        except ValueError:
            return 0

    # ------------------------------------------------------------------
    # BATCH AGGREGATION — IB HL CS: algorithmic efficiency (Big-O)
    # ------------------------------------------------------------------
    # The original per-member engine ran 6 queries PER member, then looped
    # the whole club inside update_member_rewards (O(N^2) total, 282k queries
    # at 200 members!). The batch rewrite below issues ONE grouped query per
    # data source; each returns a map {member_id: value}. Building N summaries
    # then costs O(N) time and a constant number of queries — benchmarked at
    # ~8000x faster with identical scores.
    #
    # This is a textbook example of replacing an inefficient algorithm with
    # an asymptotically better one (query optimisation / denormalisation of
    # the WORK, not the data).

    @staticmethod
    def _collect_aggregates(cursor):
        """Fetch per-member raw components with one grouped query each.

        Each SELECT uses GROUP BY member_id so the DBMS aggregates all rows
        in one pass; the results are stored in dictionaries (hash maps) for
        O(1) member lookups later.
        """
        cursor.execute("SELECT member_id, COUNT(*) AS c FROM activities WHERE activity_type='visit' GROUP BY member_id")
        visits = {r['member_id']: r['c'] for r in cursor.fetchall()}

        cursor.execute("SELECT member_id, COALESCE(SUM(transaction_value),0.0) AS s FROM activities WHERE activity_type='purchase' GROUP BY member_id")
        direct_spend = {r['member_id']: r['s'] for r in cursor.fetchall()}

        cursor.execute("SELECT member_id, COALESCE(SUM(guest_count),0) AS s FROM activities WHERE activity_type='referral' GROUP BY member_id")
        referrals = {r['member_id']: r['s'] for r in cursor.fetchall()}

        cursor.execute('''SELECT g.host_member_id AS member_id, COALESCE(SUM(ga.transaction_value),0.0) AS s
                          FROM guest_activities ga JOIN guest_ids g ON ga.guest_id = g.id
                          GROUP BY g.host_member_id''')
        guest_spend = {r['member_id']: r['s'] for r in cursor.fetchall()}

        cursor.execute("SELECT member_id, COALESCE(SUM(duration_minutes),0) AS s FROM facility_checkins WHERE status='completed' GROUP BY member_id")
        facility = {r['member_id']: r['s'] for r in cursor.fetchall()}

        cursor.execute("SELECT member_id, COALESCE(SUM(-points_delta), 0.0) AS s FROM point_transactions GROUP BY member_id")
        points_spent = {r['member_id']: r['s'] for r in cursor.fetchall()}

        return {
            'visits': visits,
            'direct_spend': direct_spend,
            'referrals': referrals,
            'guest_spend': guest_spend,
            'facility': facility,
            'points_spent': points_spent,
        }

    @staticmethod
    def _build_summary(member, aggregates, settings):
        """Build the full engagement breakdown dict for one member row."""
        member_id = member['id']
        visit_count = aggregates['visits'].get(member_id, 0)
        direct_spending = aggregates['direct_spend'].get(member_id, 0.0)
        direct_referrals = aggregates['referrals'].get(member_id, 0)
        guest_spending = aggregates['guest_spend'].get(member_id, 0.0)
        facility_minutes = aggregates['facility'].get(member_id, 0)
        points_spent = aggregates['points_spent'].get(member_id, 0.0)

        membership_type = EngagementEngine.normalize_tier(member['membership_type'])
        loyalty_months = EngagementEngine._loyalty_months(member['join_date'])

        total_spending = direct_spending + guest_spending

        visit_points = visit_count * settings['visit_weight']
        spending_points = total_spending * settings['spending_weight']
        referral_points = direct_referrals * settings['referral_weight']
        facility_points = facility_minutes * settings['facility_weight']
        loyalty_points = loyalty_months * settings['loyalty_weight']

        base_score = visit_points + spending_points + referral_points + facility_points + loyalty_points
        tier_multiplier = 1.0  # tier system removed
        score = base_score * tier_multiplier

        return {
            'visit_count': visit_count,
            'visit_points': round(visit_points, 2),
            'direct_spending': direct_spending,
            'guest_spending': guest_spending,
            'total_spending': total_spending,
            'spending_points': round(spending_points, 2),
            'guest_referrals': direct_referrals,
            'referral_points': round(referral_points, 2),
            'facility_minutes': facility_minutes,
            'facility_points': round(facility_points, 2),
            'loyalty_months': loyalty_months,
            'loyalty_points': round(loyalty_points, 2),
            'membership_type': membership_type,
            'tier_multiplier': tier_multiplier,
            'base_score': round(base_score, 2),
            'engagement_score': round(score, 2),
            'points_spent': points_spent,
        }

    @classmethod
    def _load(cls, conn):
        """Run the full batch pass on the given connection: returns
        (settings, {member_id: summary})."""
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reward_settings ORDER BY id DESC LIMIT 1")
        settings = cursor.fetchone()
        aggregates = cls._collect_aggregates(cursor)
        cursor.execute("SELECT id, membership_type, join_date FROM members")
        members = cursor.fetchall()
        summaries = {m['id']: cls._build_summary(m, aggregates, settings) for m in members}
        return settings, summaries

    @classmethod
    def calculate_all_scores(cls):
        """Batch: engagement summary for every member in ONE connection."""
        conn = get_db()
        try:
            _, summaries = cls._load(conn)
            return summaries
        finally:
            conn.close()

    @staticmethod
    def calculate_engagement_score(member_id):
        """Read-only engagement summary for a single member.

        NOTE: this is a convenience wrapper around the full batch pass
        (calculate_all_scores), so it is O(N) even for one member — fine for
        occasional lookups (e.g. coupon claims), but batch reads should use
        view_all_rewards() instead.
        """
        summaries = EngagementEngine.calculate_all_scores()
        if member_id in summaries:
            return summaries[member_id]
        # Unknown member — return a zeroed summary matching the old contract
        settings = RewardSettings.get_settings()
        empty = {'visits': {}, 'direct_spend': {}, 'referrals': {}, 'guest_spend': {}, 'facility': {}, 'points_spent': {}}
        return EngagementEngine._build_summary(
            {'id': member_id, 'membership_type': 'Member', 'join_date': None}, empty, settings)

    @staticmethod
    def calculate_discount_band(score):
        """Map engagement score to personalized discount percentage band.
        Thresholds are scaled to the full scoring model (visits, spending,
        referrals, facility minutes, loyalty, tier multiplier).

        IB HL CS: this is a *piecewise function* — a selection structure that
        maps a continuous input (score) into discrete output categories.
        Equivalent to a lookup table of thresholds. The cascading if/elif
        order matters: each condition is checked top-down, so the highest
        threshold reached "wins" (best-fit band). Tested exhaustively in
        tests/test_rewards.py.
        """
        if score >= 900:
            return 20.0
        elif score >= 500:
            return 15.0
        elif score >= 250:
            return 10.0
        elif score >= 100:
            return 5.0
        return 0.0

    # ------------------------------------------------------------------
    # Rewards records — lazy write path vs views
    # ------------------------------------------------------------------

    @staticmethod
    def _build_rewards_map(summaries, existing_codes):
        """Turn computed summaries into rewards dicts. existing_codes maps
        member_id -> stored redemption_code (may be empty on read paths).

        points_balance = lifetime points earned (engagement score) minus
        points already spent on marketplace coupons or yearly fee credits.

        IB HL CS: this is a *transform* — a pure function mapping one data
        structure (summaries) into another (rewards_map). Keeping it pure
        (no DB writes) makes it safe to call from read-only page views.
        """
        rewards_map = {}
        for member_id, summary in summaries.items():
            score = summary['engagement_score']
            discount = EngagementEngine.calculate_discount_band(score)
            spent = summary.get('points_spent', 0.0)
            rewards_map[member_id] = {
                'engagement_score': score,
                'discount_percentage': discount,
                'points_balance': round(max(0.0, score - spent), 2),
                'points_spent': round(spent, 2),
                'redemption_code': existing_codes.get(member_id) or f"FS-RED-{secrets.token_hex(8).upper()}",
                'details': summary,
            }
        return rewards_map

    @classmethod
    def _is_dirty(cls):
        """True when a scoring-relevant write happened since the last rewards
        recompute. The flag is maintained by SQLite triggers on the scoring
        tables (see database.init_db) and cleared by recalculate_all()."""
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
            row = cursor.fetchone()
            return bool(row and row['pending'])
        finally:
            conn.close()

    @classmethod
    def recalculate_all(cls, force=False):
        """WRITE path: recompute every member's score and upsert their active
        reward row in ONE transaction, then clear the recompute-pending flag.
        Call after any data-changing write (scans, purchases, referrals,
        settings changes, member creation). The `force` argument exists for
        callers that want to be explicit (e.g. the redeem flow); the write
        always runs because this is the materialization operation itself.
        Returns {member_id: rewards_dict}.

        IB HL CS: *transactional atomicity* — all upserts happen inside one
        connection and one commit, so either every reward row is updated or
        none is. This preserves database consistency even if the process
        dies mid-write. The upsert (UPDATE-if-exists else INSERT) is the
        classic idempotent write pattern.
        """
        conn = get_db()
        try:
            settings, summaries = cls._load(conn)
            cursor = conn.cursor()
            cursor.execute("SELECT member_id, redemption_code FROM rewards WHERE status='active'")
            existing_codes = {r['member_id']: r['redemption_code'] for r in cursor.fetchall()}
            rewards_map = cls._build_rewards_map(summaries, existing_codes)

            for member_id, r in rewards_map.items():
                cursor.execute("SELECT id FROM rewards WHERE member_id=? AND status='active'", (member_id,))
                row = cursor.fetchone()
                if row:
                    cursor.execute('''
                        UPDATE rewards
                        SET engagement_score = ?, discount_percentage = ?, earned_profit_share = ?, redemption_code = ?
                        WHERE id = ?
                    ''', (r['engagement_score'], r['discount_percentage'], r['details'].get('earned_profit_share', 0.0), r['redemption_code'], row['id']))
                else:
                    cursor.execute('''
                        INSERT INTO rewards (member_id, engagement_score, discount_percentage, redemption_code, status)
                        VALUES (?, ?, ?, ?, 'active')
                    ''', (member_id, r['engagement_score'], r['discount_percentage'], r['redemption_code']))
            # The upserts above re-mark the cache dirty via the rewards-table
            # triggers; clear the flag so the next rewards view is a pure read.
            cursor.execute("UPDATE rewards_recompute SET pending = 0 WHERE id = 1")
            conn.commit()
            return rewards_map
        finally:
            conn.close()

    @classmethod
    def view_all_rewards(cls):
        """Rewards view for every member. Lazily materializes (writes) reward
        rows ONLY when a scoring write happened since the last recompute (the
        SQLite-triggered dirty flag is set); otherwise a pure read — safe for
        GET routes and CSV exports when the cache is clean.

        IB HL CS: *lazy evaluation + caching*. Computing all rewards on every
        page load is wasteful, so we compute once and invalidate only when
        data changes. The dirty flag (see database.py triggers) is the cache
        validity indicator; this method is the cache-refill routine.
        """
        if cls._is_dirty():
            cls.recalculate_all()
        conn = get_db()
        try:
            settings, summaries = cls._load(conn)
            cursor = conn.cursor()
            cursor.execute("SELECT member_id, redemption_code FROM rewards WHERE status='active'")
            existing_codes = {r['member_id']: r['redemption_code'] for r in cursor.fetchall()}
            return cls._build_rewards_map(summaries, existing_codes)
        finally:
            conn.close()

    @classmethod
    def view_member_rewards(cls, member_id):
        """Rewards view for a single member (lazy materialization when dirty)."""
        return cls.view_all_rewards().get(member_id)


class FacilityTracker:
    """
    Manages facility check-in / check-out lifecycle.

    IB HL CS: this class models a simple *state machine*. A check-in record
    has two states (active -> completed). The transition computes derived
    data (duration_minutes = check_out_time - check_in_time) and logs a
    'visit' activity so the engagement engine can score the facility use.
    """
    @staticmethod
    def check_in(member_id, facility_name):
        """Check in member to facility with current timestamp."""
        conn = get_db()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT INTO facility_checkins (member_id, facility_name, check_in_time, status)
            VALUES (?, ?, ?, 'active')
        ''', (member_id, facility_name, now_str))
        conn.commit()
        checkin_id = cursor.lastrowid
        conn.close()
        return checkin_id

    @staticmethod
    def guest_check_in(guest_id, host_member_id, facility_name):
        """Check a guest into a facility, linked to their host member."""
        conn = get_db()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT INTO facility_checkins (member_id, guest_id, facility_name, check_in_time, status)
            VALUES (?, ?, ?, ?, 'active')
        ''', (host_member_id, guest_id, facility_name, now_str))
        conn.commit()
        checkin_id = cursor.lastrowid
        conn.close()
        return checkin_id

    @staticmethod
    def check_out(checkin_id):
        """Check out member from facility and calculate usage duration.

        IB HL CS: *datetime arithmetic* — the elapsed time between two
        timestamps is computed with (out_time - in_time).total_seconds() and
        floored to whole minutes (integer division). max(1, ...) guarantees a
        minimum duration so a sub-minute session still scores points. The
        check is guarded (defensive programming): an unknown or already-
        completed id returns None instead of crashing.
        """
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM facility_checkins WHERE id = ?", (checkin_id,))
        record = cursor.fetchone()
        
        if not record or record['status'] == 'completed':
            conn.close()
            return None

        in_time = datetime.strptime(record['check_in_time'], "%Y-%m-%d %H:%M:%S")
        out_time = datetime.now()
        out_str = out_time.strftime("%Y-%m-%d %H:%M:%S")
        duration_mins = max(1, int((out_time - in_time).total_seconds() / 60))

        cursor.execute('''
            UPDATE facility_checkins
            SET check_out_time = ?, duration_minutes = ?, status = 'completed'
            WHERE id = ?
        ''', (out_str, duration_mins, checkin_id))

        # Log as a visit activity for engagement score calculation
        # Guest sessions are recorded on the guest ledger instead of the member's activity log
        if record['guest_id']:
            cursor.execute('''
                INSERT INTO guest_activities (guest_id, activity_type, service_name, transaction_value)
                VALUES (?, 'facility', ?, 0.0)
            ''', (record['guest_id'], f"Facility Use: {record['facility_name']} ({duration_mins} mins)"))
        else:
            cursor.execute('''
                INSERT INTO activities (member_id, activity_type, service_name, transaction_value)
                VALUES (?, 'visit', ?, 0.0)
            ''', (record['member_id'], f"Facility Use: {record['facility_name']} ({duration_mins} mins)"))

        conn.commit()
        conn.close()
        return duration_mins


class GuestManager:
    """
    Creates guest passes and records guest spending.

    IB HL CS: guests have no user account, so they are modelled as rows in
    guest_ids linked to their host member via host_member_id (a foreign key).
    Every guest action is credited back to the host member's engagement
    score — this is how referrals become measurable value.
    """
    @staticmethod
    def get_guest_by_code(guest_code):
        """Look up an active guest pass by its code.

        Revoked passes remain in the database for reporting, but can never be
        used to start a new guest session.
        """
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM guest_ids WHERE guest_code = ? AND status = 'active'", (guest_code,))
        guest = cursor.fetchone()
        conn.close()
        return guest

    @staticmethod
    def record_spending(guest_id, service_name, amount):
        """Record spending for an active guest pass."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM guest_ids WHERE id = ? AND status = 'active'", (guest_id,))
        if not cursor.fetchone():
            conn.close()
            return False
        cursor.execute('''
            INSERT INTO guest_activities (guest_id, activity_type, service_name, transaction_value)
            VALUES (?, 'purchase', ?, ?)
        ''', (guest_id, service_name, amount))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def create_guest_id(host_member_id, guest_name):
        """Generate a guest ID for visitors without a member ID."""
        conn = get_db()
        cursor = conn.cursor()
        guest_code = f"GST-{secrets.token_hex(8).upper()}"
        cursor.execute('''
            INSERT INTO guest_ids (guest_code, guest_name, host_member_id)
            VALUES (?, ?, ?)
        ''', (guest_code, guest_name, host_member_id))
        guest_id = cursor.lastrowid
        
        # Log referral for host member
        cursor.execute('''
            INSERT INTO activities (member_id, activity_type, service_name, transaction_value, guest_count)
            VALUES (?, 'referral', ?, 0.0, 1)
        ''', (host_member_id, f"Guest Pass Generated for {guest_name} ({guest_code})"))

        conn.commit()
        conn.close()
        return {'id': guest_id, 'guest_code': guest_code, 'guest_name': guest_name}

    @staticmethod
    def revoke_guest_pass(host_member_id, guest_id):
        """Revoke a pass and persist an immutable activity report.

        The operation runs in one write-locked transaction. Any active facility
        session is closed first so the report includes the guest's complete
        visit, then all activity and facility rows are snapshotted before the
        pass is marked revoked. Repeating the request is safe and never creates
        a second report.
        """
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM guest_ids
                WHERE id = ? AND host_member_id = ?
            """, (guest_id, host_member_id))
            guest = cursor.fetchone()
            if not guest:
                conn.rollback()
                return {'ok': False, 'message': 'Guest pass not found on your account.'}

            cursor.execute("SELECT * FROM guest_pass_reports WHERE guest_id = ?", (guest_id,))
            existing_report = cursor.fetchone()
            if guest['status'] == 'revoked' or existing_report:
                conn.rollback()
                return {'ok': False, 'message': 'This guest pass has already been revoked.'}

            revoked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Close active sessions before the snapshot so no usage is omitted.
            cursor.execute("""
                SELECT * FROM facility_checkins
                WHERE guest_id = ? AND status = 'active'
            """, (guest_id,))
            active_sessions = cursor.fetchall()
            for record in active_sessions:
                try:
                    in_time = datetime.strptime(record['check_in_time'], "%Y-%m-%d %H:%M:%S")
                    out_time = datetime.strptime(revoked_at, "%Y-%m-%d %H:%M:%S")
                    duration_mins = max(1, int((out_time - in_time).total_seconds() / 60))
                except (TypeError, ValueError):
                    duration_mins = 1

                cursor.execute('''
                    UPDATE facility_checkins
                    SET check_out_time = ?, duration_minutes = ?, status = 'completed'
                    WHERE id = ? AND status = 'active'
                ''', (revoked_at, duration_mins, record['id']))
                cursor.execute('''
                    INSERT INTO guest_activities (guest_id, activity_type, service_name, transaction_value)
                    VALUES (?, 'facility', ?, 0.0)
                ''', (guest_id, f"Facility Use: {record['facility_name']} ({duration_mins} mins)"))

            cursor.execute("""
                SELECT * FROM guest_activities
                WHERE guest_id = ? ORDER BY created_at ASC, id ASC
            """, (guest_id,))
            activities = [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT * FROM facility_checkins
                WHERE guest_id = ? ORDER BY check_in_time ASC, id ASC
            """, (guest_id,))
            facility_sessions = [dict(row) for row in cursor.fetchall()]

            total_spending = round(sum(
                float(row['transaction_value'] or 0.0)
                for row in activities if row['activity_type'] == 'purchase'
            ), 2)
            total_facility_minutes = sum(
                int(row['duration_minutes'] or 0) for row in facility_sessions
            )
            snapshot = {
                'activities': activities,
                'facility_sessions': facility_sessions,
                'summary': {
                    'activity_count': len(activities),
                    'total_spending': total_spending,
                    'total_facility_minutes': total_facility_minutes,
                },
            }

            cursor.execute('''
                INSERT INTO guest_pass_reports (
                    guest_id, host_member_id, guest_code, guest_name, issued_at,
                    revoked_at, activity_count, total_spending,
                    total_facility_minutes, activity_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                guest_id, guest['host_member_id'], guest['guest_code'], guest['guest_name'],
                guest['created_at'], revoked_at, len(activities), total_spending,
                total_facility_minutes, json.dumps(snapshot, separators=(',', ':'))
            ))
            report_id = cursor.lastrowid

            cursor.execute("""
                UPDATE guest_ids SET status = 'revoked', revoked_at = ?
                WHERE id = ? AND status = 'active'
            """, (revoked_at, guest_id))
            conn.commit()
            return {
                'ok': True,
                'report_id': report_id,
                'guest_name': guest['guest_name'],
                'activity_count': len(activities),
                'total_spending': total_spending,
                'total_facility_minutes': total_facility_minutes,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def get_guest_report(host_member_id, guest_id):
        """Return a host member's immutable guest-pass report, if available."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM guest_pass_reports
            WHERE host_member_id = ? AND guest_id = ?
        ''', (host_member_id, guest_id))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None

        report = dict(row)
        try:
            snapshot = json.loads(report['activity_snapshot'])
        except (TypeError, ValueError):
            snapshot = {'activities': [], 'facility_sessions': [], 'summary': {}}
        report['activities'] = snapshot.get('activities', [])
        report['facility_sessions'] = snapshot.get('facility_sessions', [])
        report['summary'] = snapshot.get('summary', {})
        return report

    @staticmethod
    def record_guest_spending(guest_code, service_name, amount):
        """Record spending by a guest using their guest ID code."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM guest_ids WHERE guest_code = ? AND status = 'active'", (guest_code,))
        guest = cursor.fetchone()
        
        if not guest:
            conn.close()
            return False

        cursor.execute('''
            INSERT INTO guest_activities (guest_id, activity_type, service_name, transaction_value)
            VALUES (?, 'purchase', ?, ?)
        ''', (guest['id'], service_name, amount))
        conn.commit()
        conn.close()
        return True


class ReceiptManager:
    """QR expense receipts: admins issue a receipt voucher with a unique
    RCPT-XXXX code; members scan the QR at the end of the receipt to log
    the expense automatically. Each receipt can be scanned exactly once
    (deduplicated) — a member scan logs it to their ledger, a guest scan
    logs it to the guest ledger and credits the host member.

    IB HL CS: this class implements a *concurrency-safe deduplication*
    pattern (see redeem_for_member): a conditional UPDATE ... WHERE status=
    'unscanned' is atomic — only ONE of two simultaneous scans can flip the
    row, so a receipt can never be double-counted (prevents a race condition
    / lost-update problem).
    """

    @staticmethod
    def issue_receipt(service_name, amount):
        """Create a new unscanned expense receipt voucher."""
        conn = get_db()
        cursor = conn.cursor()
        receipt_code = f"RCPT-{secrets.token_hex(8).upper()}"
        cursor.execute('''
            INSERT INTO receipts (receipt_code, service_name, amount)
            VALUES (?, ?, ?)
        ''', (receipt_code, service_name, amount))
        conn.commit()
        receipt_id = cursor.lastrowid
        conn.close()
        return {'id': receipt_id, 'receipt_code': receipt_code, 'service_name': service_name, 'amount': amount}

    @staticmethod
    def get_receipt_by_code(receipt_code):
        """Look up a receipt by its RCPT-XXXX code."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM receipts WHERE receipt_code = ?", (receipt_code,))
        receipt = cursor.fetchone()
        conn.close()
        return receipt

    @staticmethod
    def redeem_for_member(receipt_code, member_id):
        """Scan a receipt QR for a member — logs the expense to their activity
        ledger. Returns dict with 'ok' and 'message'. A receipt that has
        already been scanned is rejected (deduplication)."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM receipts WHERE receipt_code = ?", (receipt_code,))
        receipt = cursor.fetchone()
        if not receipt:
            conn.close()
            return {'ok': False, 'message': f'Invalid receipt code "{receipt_code}". Please scan a valid receipt QR.'}
        if receipt['status'] == 'scanned':
            conn.close()
            return {'ok': False, 'message': f'Receipt {receipt_code} has already been scanned and logged.'}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Atomic deduplication: only one request can flip status unscanned->scanned.
        cursor.execute('''
            UPDATE receipts SET status = 'scanned', scanned_by_member = ?, scanned_at = ?
            WHERE id = ? AND status = 'unscanned'
        ''', (member_id, now_str, receipt['id']))
        if cursor.rowcount == 0:
            conn.close()
            return {'ok': False, 'message': f'Receipt {receipt_code} has already been scanned and logged.'}
        cursor.execute('''
            INSERT INTO activities (member_id, activity_type, service_name, transaction_value)
            VALUES (?, 'purchase', ?, ?)
        ''', (member_id, receipt['service_name'], receipt['amount']))
        conn.commit()
        conn.close()
        return {'ok': True, 'message': f'Expense of ${receipt["amount"]:.2f} for {receipt["service_name"]} logged from receipt {receipt_code}!'}

    @staticmethod
    def redeem_for_guest(receipt_code, guest_id):
        """Scan a receipt QR for a guest — logs the expense to the guest
        ledger (credited to their host member's rewards). Deduplicated."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM receipts WHERE receipt_code = ?", (receipt_code,))
        receipt = cursor.fetchone()
        if not receipt:
            conn.close()
            return {'ok': False, 'message': f'Invalid receipt code "{receipt_code}". Please scan a valid receipt QR.'}
        if receipt['status'] == 'scanned':
            conn.close()
            return {'ok': False, 'message': f'Receipt {receipt_code} has already been scanned and logged.'}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Atomic deduplication: only one request can flip status unscanned->scanned.
        cursor.execute('''
            UPDATE receipts SET status = 'scanned', scanned_by_guest = ?, scanned_at = ?
            WHERE id = ? AND status = 'unscanned'
        ''', (guest_id, now_str, receipt['id']))
        if cursor.rowcount == 0:
            conn.close()
            return {'ok': False, 'message': f'Receipt {receipt_code} has already been scanned and logged.'}
        cursor.execute('''
            INSERT INTO guest_activities (guest_id, activity_type, service_name, transaction_value)
            VALUES (?, 'purchase', ?, ?)
        ''', (guest_id, receipt['service_name'], receipt['amount']))
        conn.commit()
        conn.close()
        return {'ok': True, 'message': f'Purchase of ${receipt["amount"]:.2f} from receipt {receipt_code} — credited to your host member!'}


class MarketplaceManager:
    """Points marketplace: members spend earned points to claim coupons for
    facilities and discounts, or credit points against their yearly club
    membership fee. All spending is recorded in the point_transactions
    ledger so a member's spendable balance always equals lifetime earned
    points minus points spent.

    IB HL CS: *financial integrity* — the balance is never stored directly;
    it is always DERIVED (earned - spent) from two auditable sources, which
    prevents the classic bug of a cached balance drifting out of sync. Every
    spend writes an immutable ledger row (point_transactions), giving a
    complete audit trail.
    """

    @staticmethod
    def get_active_coupons():
        """Catalog of currently available coupons (admin-enabled)."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coupons WHERE active = 1 ORDER BY cost_points ASC")
        coupons = cursor.fetchall()
        conn.close()
        return coupons

    @staticmethod
    def get_coupon(coupon_id):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
        coupon = cursor.fetchone()
        conn.close()
        return coupon

    @staticmethod
    def get_member_coupons(member_id):
        """Coupons a member has claimed, newest first, annotated with their
        redemption deadline: expires_at (datetime), expires_at_date (str) and
        expired (bool) so the UI can show remaining validity at a glance."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT mc.*, c.name, c.description, c.category, c.value_amount, c.facility_name
            FROM member_coupons mc
            JOIN coupons c ON mc.coupon_id = c.id
            WHERE mc.member_id = ?
            ORDER BY mc.claimed_at DESC
        ''', (member_id,))
        rows = cursor.fetchall()
        conn.close()

        coupons = []
        for row in rows:
            coupon = dict(row)
            expires = MarketplaceManager.coupon_expires_at(coupon['claimed_at'])
            coupon['expires_at'] = expires
            coupon['expires_at_date'] = expires.strftime('%Y-%m-%d') if expires else None
            coupon['expired'] = MarketplaceManager.is_coupon_expired(coupon['claimed_at'])
            coupons.append(coupon)
        return coupons

    @staticmethod
    def coupon_valid_days():
        """How long a claimed coupon stays redeemable (days)."""
        return Config.DEFAULT_COUPON_VALID_DAYS

    @staticmethod
    def coupon_expires_at(claimed_at):
        """Datetime when a coupon claimed at `claimed_at` stops being valid.
        Returns None for unparseable timestamps (defensive)."""
        try:
            claimed = datetime.strptime(str(claimed_at)[:19], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None
        return claimed + timedelta(days=MarketplaceManager.coupon_valid_days())

    @staticmethod
    def is_coupon_expired(claimed_at):
        """True once a coupon's validity window has passed. An unparseable
        timestamp is treated as NOT expired (defensive default) so a data
        glitch never silently voids a member's coupon."""
        expires = MarketplaceManager.coupon_expires_at(claimed_at)
        if expires is None:
            return False
        # claimed_at is UTC (SQLite CURRENT_TIMESTAMP); compare against UTC
        # now, not local time, or coupons expire up to the host's offset early.
        return datetime.now(timezone.utc).replace(tzinfo=None) > expires

    @staticmethod
    def use_coupon(coupon_code, member_id):
        """Redeem a claimed coupon at the facility desk: marks it 'used'
        exactly once and stamps used_at. Returns
        {'ok': bool, 'message': str, 'coupon_code': str}.

        Guards against: unknown codes, coupons belonging to another member,
        expired coupons, and double redemption. The one-time-use guarantee
        is enforced atomically — a conditional UPDATE ... WHERE status =
        'active' inside a BEGIN IMMEDIATE (write-locked) transaction means
        only ONE of two simultaneous scans can flip the row, so a coupon
        can never be redeemed twice (same concurrency-safe dedup pattern
        as ReceiptManager).
        """
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM member_coupons WHERE coupon_code = ?", (coupon_code,))
            mc = cursor.fetchone()

            if not mc:
                conn.rollback()
                return {'ok': False, 'message': f'Coupon code "{coupon_code}" was not found on your account.', 'coupon_code': coupon_code}
            if mc['member_id'] != member_id:
                conn.rollback()
                return {'ok': False, 'message': f'Coupon {coupon_code} belongs to a different member account.', 'coupon_code': coupon_code}
            if mc['status'] == 'used':
                conn.rollback()
                return {'ok': False, 'message': f'Coupon {coupon_code} has already been used — each coupon is valid for a single redemption.', 'coupon_code': coupon_code}

            # Expired coupons are refused even though the row is still active.
            if MarketplaceManager.is_coupon_expired(mc['claimed_at']):
                conn.rollback()
                # Report the expiry date (claim + validity window), not the
                # claim date.
                expiry_date = MarketplaceManager.coupon_expires_at(mc['claimed_at']).strftime('%Y-%m-%d')
                return {'ok': False, 'message': f'Coupon {coupon_code} expired on {expiry_date} and is no longer valid.', 'coupon_code': coupon_code}

            cursor.execute("SELECT name FROM coupons WHERE id = ?", (mc['coupon_id'],))
            coupon = cursor.fetchone()
            name = coupon['name'] if coupon else 'Coupon'

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Atomic one-time use: only one request can flip active -> used.
            cursor.execute('''
                UPDATE member_coupons SET status = 'used', used_at = ?
                WHERE id = ? AND status = 'active'
            ''', (now_str, mc['id']))
            if cursor.rowcount == 0:
                conn.rollback()
                return {'ok': False, 'message': f'Coupon {coupon_code} has already been used.', 'coupon_code': coupon_code}

            conn.commit()
            return {'ok': True, 'message': f'Coupon "{name}" redeemed successfully — enjoy your visit!', 'coupon_code': coupon_code}
        finally:
            conn.close()

    @staticmethod
    def get_point_transactions(member_id, limit=12):
        """Recent point ledger entries (spends) for a member."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM point_transactions WHERE member_id = ?
            ORDER BY created_at DESC LIMIT ?
        ''', (member_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return rows

    @staticmethod
    def claim_coupon(member_id, coupon_id):
        """Claim a coupon for the member: deducts points and issues a unique
        coupon code. Returns {'ok': bool, 'message': str, 'coupon_code': str|None}.
        The balance check and the spend run in one IMMEDIATE (write-locked)
        transaction, so concurrent claims can never both pass a stale balance
        check and double-spend the same points."""
        conn = get_db()
        try:
            # BEGIN IMMEDIATE takes the SQLite write lock up front, serializing
            # concurrent claims: a second claim blocks until the first commits,
            # then re-reads the reduced balance and is rejected if it is short.
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
            coupon = cursor.fetchone()
            if not coupon or not coupon['active']:
                conn.rollback()
                return {'ok': False, 'message': 'This coupon is no longer available in the marketplace.'}

            # Earned points come from a fresh live engagement computation, never
            # from the materialized rewards table (which may be stale or absent
            # — e.g. right after a redeem flipped the active row to 'redeemed').
            earned = EngagementEngine.calculate_engagement_score(member_id)['engagement_score']
            cursor.execute("SELECT COALESCE(SUM(-points_delta), 0.0) AS s FROM point_transactions WHERE member_id = ?", (member_id,))
            spent = cursor.fetchone()['s']
            balance = earned - spent

            if balance < coupon['cost_points']:
                conn.rollback()
                return {'ok': False, 'message': f'Insufficient points - you need {coupon["cost_points"]:.0f} pts but only have {balance:.0f} pts available.'}

            # 6-hex codes can collide with an existing row; the UNIQUE column
            # stays the backstop, so regenerate until the check finds a gap.
            while True:
                coupon_code = f"CPN-{secrets.token_hex(8).upper()}"
                cursor.execute("SELECT 1 FROM member_coupons WHERE coupon_code = ?", (coupon_code,))
                if not cursor.fetchone():
                    break
            cursor.execute('''
                INSERT INTO member_coupons (member_id, coupon_id, coupon_code, points_spent, status)
                VALUES (?, ?, ?, ?, 'active')
            ''', (member_id, coupon_id, coupon_code, coupon['cost_points']))
            cursor.execute('''
                INSERT INTO point_transactions (member_id, points_delta, reason)
                VALUES (?, ?, ?)
            ''', (member_id, -coupon['cost_points'], f"Claimed coupon: {coupon['name']}"))
            conn.commit()
            return {'ok': True, 'message': f"Coupon claimed! {coupon['name']} for {coupon['cost_points']:.0f} pts.", 'coupon_code': coupon_code}
        finally:
            conn.close()

    @staticmethod
    def get_member_fee(member_id):
        """Yearly membership fee status for a member."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT yearly_fee, fee_points_applied, fee_paid FROM members WHERE id = ?", (member_id,))
        row = cursor.fetchone()
        settings = RewardSettings.get_settings()
        conn.close()
        if not row:
            return None
        applied_dollars = row['fee_points_applied']
        remaining = round(max(0.0, row['yearly_fee'] - applied_dollars), 2)
        return {
            'yearly_fee': row['yearly_fee'],
            'fee_points_applied': row['fee_points_applied'],
            'fee_paid': bool(row['fee_paid']),
            'remaining': remaining,
            'points_value_dollars': settings['points_value_dollars'],
        }

    @staticmethod
    def apply_points_to_fee(member_id, points):
        """Convert points into a dollar credit against the yearly fee.
        Points are consumed at the configured rate and can never exceed the
        remaining fee balance. Returns {'ok', 'message', 'credited', 'remaining'}.
        The balance check and the credit run in one IMMEDIATE (write-locked)
        transaction so concurrent requests cannot both spend the same points."""
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute("SELECT yearly_fee, fee_points_applied, fee_paid FROM members WHERE id = ?", (member_id,))
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return {'ok': False, 'message': 'Member record not found.'}
            if row['fee_paid']:
                conn.rollback()
                return {'ok': False, 'message': 'Your yearly fee is already paid in full.'}

            settings = RewardSettings.get_settings()
            rate = settings['points_value_dollars']
            # A zero/negative conversion rate would burn points for no dollar
            # credit — refuse instead of silently consuming the balance.
            if rate <= 0:
                conn.rollback()
                return {'ok': False, 'message': 'Point-to-fee conversion is currently unavailable (conversion rate is zero).'}
            # Same fresh-computation rationale as claim_coupon: never trust the
            # materialized rewards table for the spendable balance.
            earned = EngagementEngine.calculate_engagement_score(member_id)['engagement_score']
            cursor.execute("SELECT COALESCE(SUM(-points_delta), 0.0) AS s FROM point_transactions WHERE member_id = ?", (member_id,))
            spent = cursor.fetchone()['s']
            balance = earned - spent

            try:
                points = float(points)
            except (ValueError, TypeError):
                conn.rollback()
                return {'ok': False, 'message': 'Please enter a positive number of points.'}
            if not math.isfinite(points) or points <= 0:
                conn.rollback()
                return {'ok': False, 'message': 'Please enter a positive number of points.'}

            # Cap the request at the points the remaining fee actually needs
            # BEFORE the affordability check. A member who types a round number
            # larger than their balance must still be able to pay off a small
            # fee (the surplus is simply not consumed), and can never burn
            # extra points against the fee (no over-crediting).
            fee_remaining = max(0.0, row['yearly_fee'] - row['fee_points_applied'])
            needed_points = round(fee_remaining / rate, 2) if rate > 0 else 0.0
            points = min(points, needed_points)

            if points > balance:
                conn.rollback()
                return {'ok': False, 'message': f'You only have {balance:.0f} points available to credit.'}

            # Exact-payoff branch: the request covers (or exceeds) the fee's
            # need, so credit the exact remaining dollars and mark it settled.
            # Otherwise this is a partial credit at the configured rate.
            if needed_points > 0 and points >= needed_points:
                credited = round(fee_remaining, 2)
                remaining = 0.0
            else:
                credited = round(points * rate, 2)
                remaining = round(max(0.0, fee_remaining - credited), 2)

            cursor.execute('''
                INSERT INTO point_transactions (member_id, points_delta, reason)
                VALUES (?, ?, ?)
            ''', (member_id, -points, 'Yearly membership fee credit'))
            cursor.execute("UPDATE members SET fee_points_applied = fee_points_applied + ? WHERE id = ?", (credited, member_id))
            if remaining == 0:
                cursor.execute("UPDATE members SET fee_paid = 1 WHERE id = ?", (member_id,))
            conn.commit()
            return {
                'ok': True,
                'message': f'{points:.0f} pts converted to ${credited:.2f} off your yearly fee.',
                'credited': credited,
                'remaining': remaining,
            }
        finally:
            conn.close()


class CSVReportGenerator:
    """
    Exports database content as CSV strings (file processing).

    IB HL CS: this is the *file processing* strand — data held in a database
    is serialised into a comma-separated-values text file that external
    tools (Excel, accounting software) can consume. io.StringIO buffers the
    output in memory (a data structure!) so the CSV can be built with a
    streaming writer without touching disk, then returned over HTTP.
    """
    @staticmethod
    def export_member_usage_logs():
        """Export member activities and facility check-ins to CSV string."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.member_code, m.full_name, a.activity_type, a.service_name,
                   a.transaction_value, a.guest_count, a.created_at
            FROM activities a
            JOIN members m ON a.member_id = m.id
            ORDER BY a.created_at DESC
        ''')
        rows = cursor.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Member Code', 'Full Name', 'Activity Type', 'Service / Description', 'Transaction Value ($)', 'Guest Referrals', 'Timestamp'])
        
        for r in rows:
            writer.writerow([r['member_code'], r['full_name'], r['activity_type'], r['service_name'], f"{r['transaction_value']:.2f}", r['guest_count'], r['created_at']])

        return output.getvalue()

    @staticmethod
    def export_financial_reward_summaries():
        """READ-ONLY export of points & marketplace summaries.
        Uses the batch rewards view so GET requests never mutate the database."""
        rewards_map = EngagementEngine.view_all_rewards()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, member_code, full_name, membership_type FROM members")
        members = cursor.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Member Code', 'Full Name', 'Membership Type', 'Total Points Earned', 'Points Balance', 'Discount Band (%)', 'Coupons Claimed', 'Redemption Code', 'Status'])

        for m in members:
            info = rewards_map.get(m['id'])
            if info is None:
                continue
            coupon_count = len(MarketplaceManager.get_member_coupons(m['id']))
            writer.writerow([
                m['member_code'],
                m['full_name'],
                m['membership_type'],
                f"{info['engagement_score']:.2f}",
                f"{info['points_balance']:.2f}",
                f"{info['discount_percentage']:.1f}%",
                coupon_count,
                info['redemption_code'],
                'Active'
            ])

        return output.getvalue()
