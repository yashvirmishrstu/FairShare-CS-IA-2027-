import pytest
import os
from database import init_db, get_db
from models import EngagementEngine, RewardSettings, FacilityTracker, GuestManager, CSVReportGenerator

@pytest.fixture(autouse=True)
def setup_test_database(tmp_path, monkeypatch):
    """Set up temporary SQLite database for testing."""
    test_db = os.path.join(tmp_path, "test_fairshare.db")
    monkeypatch.setattr('config.Config.DATABASE', test_db)
    init_db()
    yield test_db

def test_engagement_score_and_discount_calculation():
    conn = get_db()
    cursor = conn.cursor()
    
    # Get test member Alice
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()

    summary = EngagementEngine.calculate_engagement_score(alice_id)
    # Alice has 1 visit (10 pts), $180.50 spending (90.25 pts), 2 referrals (100 pts)
    assert summary['engagement_score'] > 0
    assert summary['visit_count'] >= 1
    assert summary['visit_points'] >= 10.0
    assert summary['spending_points'] >= 90.0
    assert summary['referral_points'] >= 100.0
    # All data sources are present in the breakdown
    assert 'facility_minutes' in summary
    assert 'facility_points' in summary
    assert 'loyalty_months' in summary
    assert 'loyalty_points' in summary
    assert 'tier_multiplier' in summary
    assert summary['tier_multiplier'] == 1.0
    assert summary['base_score'] > 0
    assert summary['engagement_score'] == round(summary['base_score'] * summary['tier_multiplier'], 2)

    discount = EngagementEngine.calculate_discount_band(summary['engagement_score'])
    assert discount in [0.0, 5.0, 10.0, 15.0, 20.0]

def test_facility_checkin_checkout_duration():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    conn.close()

    checkin_id = FacilityTracker.check_in(m_id, "Gym & Fitness")
    assert checkin_id is not None

    duration = FacilityTracker.check_out(checkin_id)
    assert duration >= 1

def test_guest_facility_checkin_checkout_logs_on_guest_ledger():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    host_id = cursor.fetchone()['id']
    conn.close()

    guest_res = GuestManager.create_guest_id(host_id, "Fiona Visitor")
    guest_id = guest_res['id']

    # Guest checks into a facility linked to their host member
    checkin_id = FacilityTracker.guest_check_in(guest_id, host_id, "Swimming Pool & Spa")
    assert checkin_id is not None
    duration = FacilityTracker.check_out(checkin_id)
    assert duration >= 1

    # Guest session lands on the guest ledger, NOT the host member's activity log
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM guest_activities WHERE guest_id = ? AND activity_type = 'facility'", (guest_id,))
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM activities WHERE member_id = ? AND service_name LIKE 'Facility Use%'", (host_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()

def test_guest_creation_and_spending():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    host_id = cursor.fetchone()['id']
    conn.close()

    guest_res = GuestManager.create_guest_id(host_id, "David Miller")
    assert guest_res['guest_code'].startswith("GST-")

    success = GuestManager.record_guest_spending(guest_res['guest_code'], "Tennis Shop", 150.00)
    assert success is True

    # Verify that guest spending is reflected in host member engagement calculation
    summary = EngagementEngine.calculate_engagement_score(host_id)
    assert summary['guest_spending'] >= 150.00

def test_facility_usage_minutes_add_points():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    conn.close()

    # Baseline facility points (seed data has no completed check-ins)
    baseline = EngagementEngine.calculate_engagement_score(m_id)

    # Complete a facility session
    checkin_id = FacilityTracker.check_in(m_id, "Gym & Fitness")
    FacilityTracker.check_out(checkin_id)

    summary = EngagementEngine.calculate_engagement_score(m_id)
    assert summary['facility_minutes'] > baseline['facility_minutes']
    assert summary['facility_points'] >= baseline['facility_points']
    assert summary['engagement_score'] > baseline['engagement_score']

def test_loyalty_months_award_points():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    # Backdate the join date to 6 months ago to simulate a loyal member
    from datetime import datetime, timedelta
    old_join = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    cursor.execute("UPDATE members SET join_date = ? WHERE id = ?", (old_join, m_id))
    conn.commit()
    conn.close()

    summary = EngagementEngine.calculate_engagement_score(m_id)
    assert summary['loyalty_months'] >= 5
    assert summary['loyalty_points'] >= summary['loyalty_months'] * 5.0

def test_membership_tier_multiplier_boosts_score():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    cursor.execute("UPDATE members SET membership_type = 'Premium' WHERE id = ?", (m_id,))
    conn.commit()
    conn.close()

    summary = EngagementEngine.calculate_engagement_score(m_id)
    settings = RewardSettings.get_settings()
    assert summary['membership_type'] == 'Premium'
    assert summary['tier_multiplier'] == settings['premium_multiplier']
    assert summary['engagement_score'] == round(summary['base_score'] * summary['tier_multiplier'], 2)
    assert summary['engagement_score'] >= summary['base_score']

def test_tier_normalization_and_multiplier_lookup():
    """Every tier spelling resolves to the canonical tier and its multiplier,
    and unknown tiers fall back to the base Member multiplier (1.0)."""
    settings = RewardSettings.get_settings()

    # normalize_tier: canonical spellings, mixed case, whitespace, aliases
    assert EngagementEngine.normalize_tier('Member') == 'Member'
    assert EngagementEngine.normalize_tier('Premium') == 'Premium'
    assert EngagementEngine.normalize_tier('VIP') == 'VIP'
    assert EngagementEngine.normalize_tier('premium') == 'Premium'
    assert EngagementEngine.normalize_tier('vip') == 'VIP'
    assert EngagementEngine.normalize_tier('  Premium  ') == 'Premium'
    assert EngagementEngine.normalize_tier('') == 'Member'
    assert EngagementEngine.normalize_tier(None) == 'Member'
    assert EngagementEngine.normalize_tier('Gold') == 'Member'  # unknown -> Member

    # tier_multiplier: uses the live settings values for paid tiers
    assert EngagementEngine.tier_multiplier('Member', settings) == 1.0
    assert EngagementEngine.tier_multiplier('Premium', settings) == settings['premium_multiplier']
    assert EngagementEngine.tier_multiplier('VIP', settings) == settings['vip_multiplier']
    assert EngagementEngine.tier_multiplier('premium', settings) == settings['premium_multiplier']
    assert EngagementEngine.tier_multiplier('vip ', settings) == settings['vip_multiplier']
    assert EngagementEngine.tier_multiplier('Platinum', settings) == 1.0

def test_membership_type_persists_and_multiplier_applies():
    """Changing membership_type to VIP applies the VIP multiplier from settings."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    cursor.execute("UPDATE members SET membership_type = 'VIP' WHERE id = ?", (m_id,))
    conn.commit()
    conn.close()

    settings = RewardSettings.get_settings()
    summary = EngagementEngine.calculate_engagement_score(m_id)
    assert summary['membership_type'] == 'VIP'
    assert summary['tier_multiplier'] == settings['vip_multiplier']
    assert summary['engagement_score'] == round(summary['base_score'] * settings['vip_multiplier'], 2)

def test_settings_update():
    RewardSettings.update_settings(15.0, 1.0, 60.0, 0.5, 8.0, 15000.00, 1.2, 1.5)
    settings = RewardSettings.get_settings()
    assert settings['visit_weight'] == 15.0
    assert settings['spending_weight'] == 1.0
    assert settings['referral_weight'] == 60.0
    assert settings['facility_weight'] == 0.5
    assert settings['loyalty_weight'] == 8.0
    assert settings['premium_multiplier'] == 1.2
    assert settings['vip_multiplier'] == 1.5
    assert settings['profit_sharing_pool'] == 15000.00


def test_batch_scores_match_single_member_lookup():
    """The batch pass must produce the same summary for every member as the
    per-member lookup — the grouped queries must not change the math."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members")
    member_ids = [r['id'] for r in cursor.fetchall()]
    conn.close()

    batch = EngagementEngine.calculate_all_scores()
    assert len(batch) == len(member_ids)

    for m_id in member_ids:
        assert m_id in batch, f"member {m_id} missing from batch pass"
        single = EngagementEngine.calculate_engagement_score(m_id)
        for key in ('visit_count', 'total_spending', 'guest_referrals',
                    'facility_minutes', 'loyalty_months', 'base_score',
                    'tier_multiplier', 'engagement_score'):
            assert batch[m_id][key] == single[key], \
                f"batch/single mismatch on {key} for member {m_id}"


def test_recalculate_all_upserts_rewards_and_preserves_codes():
    """recalculate_all() creates one active reward row per member and updates
    (never duplicates) them on subsequent calls, keeping redemption codes
    stable across recomputes."""
    # No reward rows exist yet
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT id FROM members")
    member_ids = [r['id'] for r in cursor.fetchall()]
    conn.close()

    rewards_map = EngagementEngine.recalculate_all()
    assert set(rewards_map.keys()) == set(member_ids)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT member_id, redemption_code FROM rewards WHERE status='active'")
    first = {r['member_id']: r['redemption_code'] for r in cursor.fetchall()}
    conn.close()
    assert len(first) == len(member_ids)  # exactly one active row per member

    # Data changes (add an activity) then recompute — rows update, codes persist
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) VALUES (?, 'purchase', 'New Purchase', 50.0)", (member_ids[0],))
    conn.commit()
    conn.close()
    EngagementEngine.recalculate_all()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT member_id, redemption_code, engagement_score FROM rewards WHERE status='active'")
    second = {r['member_id']: (r['redemption_code'], r['engagement_score']) for r in cursor.fetchall()}
    conn.close()

    assert len(second) == len(member_ids)  # no duplicate rows after recompute
    for m_id in member_ids:
        assert second[m_id][0] == first[m_id]  # redemption code survived
    # The member whose spending grew now has a higher stored score
    assert second[member_ids[0]][1] > rewards_map[member_ids[0]]['engagement_score']


def test_rewards_view_and_csv_export_are_read_only():
    """view_all_rewards() and the financial CSV export must never write to the
    database — reading a page or downloading a report is a pure GET."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards")
    assert cursor.fetchone()[0] == 0
    conn.close()

    # Both read paths run on an empty rewards table and must not create rows
    view = EngagementEngine.view_all_rewards()
    assert len(view) > 0  # summaries computed on the fly for seeded members

    csv_data = CSVReportGenerator.export_financial_reward_summaries()
    assert 'Total Points Earned' in csv_data
    assert 'Member Code' in csv_data

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards")
    assert cursor.fetchone()[0] == 0, "read-only views must not insert reward rows"
    conn.close()
