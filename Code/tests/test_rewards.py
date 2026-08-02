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
    # Alice has 1 visit (10 pts), $180.50 spending (90.25 pts), 2 referrals (100 pts) = ~200.25 pts
    assert summary['engagement_score'] > 0
    assert summary['visit_count'] >= 1

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

def test_settings_update():
    RewardSettings.update_settings(15.0, 1.0, 60.0, 15000.00)
    settings = RewardSettings.get_settings()
    assert settings['visit_weight'] == 15.0
    assert settings['spending_weight'] == 1.0
    assert settings['profit_sharing_pool'] == 15000.00
