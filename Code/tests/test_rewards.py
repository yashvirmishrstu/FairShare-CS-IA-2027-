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
