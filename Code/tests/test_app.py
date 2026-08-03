import pytest
import os
from main import app
from database import init_db, get_db
from models import EngagementEngine

@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = os.path.join(tmp_path, "test_app_fairshare.db")
    monkeypatch.setattr('config.Config.DATABASE', test_db)
    app.config['TESTING'] = True
    init_db()

    with app.test_client() as client:
        yield client

def test_home_page(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'FairShare' in response.data

def test_member_login_success(client):
    response = client.post('/login', data={
        'username': 'alice',
        'password': 'password123'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Welcome back, alice!' in response.data

def test_login_failure(client):
    response = client.post('/login', data={
        'username': 'alice',
        'password': 'wrongpassword'
    }, follow_redirects=True)
    assert b'Invalid username or password' in response.data

def test_admin_route_protection(client):
    # Unauthenticated access to admin dashboard should redirect to login
    response = client.get('/admin/dashboard', follow_redirects=True)
    assert b'Please log in to access this page' in response.data or b'Unauthorized access' in response.data

def test_admin_login_and_csv_exports(client):
    # Login as admin
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    
    # Check admin dashboard
    response = client.get('/admin/dashboard')
    assert response.status_code == 200
    assert b'Executive Dashboard' in response.data

    # Test CSV usage export
    usage_csv = client.get('/admin/reports/export/usage_csv')
    assert usage_csv.status_code == 200
    assert b'Member Code' in usage_csv.data

    # Test CSV rewards export
    rewards_csv = client.get('/admin/reports/export/rewards_csv')
    assert rewards_csv.status_code == 200
    assert b'Engagement Score' in rewards_csv.data

def test_member_scan_requires_login(client):
    response = client.get('/member/scan', follow_redirects=True)
    assert b'Please log in to access this page' in response.data

def test_member_scan_admin_redirects_not_crash(client):
    # Admins have no member profile row — the scanner page must redirect, not 500
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    response = client.get('/member/scan', follow_redirects=True)
    assert response.status_code == 200
    assert b'Member profile not found' in response.data

def test_guest_dashboard_requires_signin(client):
    # No guest session -> bounced to the unified login page's guest tab
    response = client.get('/guest/dashboard', follow_redirects=True)
    assert b'Member / Admin' in response.data
    assert b'Guest Pass Code' in response.data

def test_guest_day_pass_login_and_tracking(client):
    # Alice creates a guest pass for her guest
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    client.post('/member/guest/create', data={'guest_name': 'Diana Day'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT g.guest_code, g.id, g.host_member_id FROM guest_ids g
        JOIN members m ON g.host_member_id = m.id
        WHERE m.full_name = 'Alice Johnson' ORDER BY g.id DESC LIMIT 1
    ''')
    guest = cursor.fetchone()
    conn.close()
    guest_code = guest['guest_code']

    # Unified login page renders with the guest tab
    response = client.get('/login?tab=guest')
    assert response.status_code == 200
    assert b'Member / Admin' in response.data
    assert b'Guest Pass Code' in response.data

    # Invalid code rejected
    response = client.post('/login', data={'guest_code': 'GST-NOPE'}, follow_redirects=True)
    assert b'Invalid Guest Pass Code' in response.data

    # Valid code -> guest dashboard linked to host member
    response = client.post('/login', data={'guest_code': guest_code}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Diana Day' in response.data
    assert b'Hosted by' in response.data
    assert b'Alice Johnson' in response.data

    # Guest scans facility barcode: check in then check out
    response = client.post('/guest/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
    assert b'Checked in to Club Fitness' in response.data
    response = client.post('/guest/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
    assert b'Checked out of Club Fitness' in response.data

    # Guest records a purchase -> credited to host member
    response = client.post('/guest/spending', data={'service_name': 'Bistro Lunch', 'amount': '25.50'}, follow_redirects=True)
    assert b'credited to your host' in response.data

    # Host engagement score now reflects the guest's spending
    summary = EngagementEngine.calculate_engagement_score(guest['host_member_id'])
    assert summary['guest_spending'] >= 25.50

    # Guest ledger holds both facility + purchase rows
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM guest_activities WHERE guest_id = ?", (guest['id'],))
    assert cursor.fetchone()[0] >= 2
    conn.close()

def test_guest_quick_checkin_and_purchase(client):
    # Alice creates a guest pass for her guest
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    client.post('/member/guest/create', data={'guest_name': 'Diana Day'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT g.guest_code, g.id, g.host_member_id FROM guest_ids g
        JOIN members m ON g.host_member_id = m.id
        WHERE m.full_name = 'Alice Johnson' ORDER BY g.id DESC LIMIT 1
    ''')
    guest = cursor.fetchone()
    conn.close()
    guest_code = guest['guest_code']

    # Quick page renders with the combined check-in & purchase card
    response = client.get('/guest/quick')
    assert response.status_code == 200
    assert b'Quick Guest Check-In' in response.data
    assert b'Guest Pass Code' in response.data
    assert b'Facility Service Used' in response.data
    assert b'Transaction Amount' in response.data

    # Invalid code rejected
    response = client.post('/guest/quick', data={
        'guest_code': 'GST-NOPE', 'service_name': 'Bistro Lunch', 'amount': '25.50'
    }, follow_redirects=True)
    assert b'Invalid Guest Pass Code' in response.data

    # Negative amount rejected
    response = client.post('/guest/quick', data={
        'guest_code': guest_code, 'service_name': 'Bistro Lunch', 'amount': '-5.00'
    }, follow_redirects=True)
    assert b'cannot be negative' in response.data

    # Valid code + purchase -> guest signed in, redirected to tracking dashboard
    response = client.post('/guest/quick', data={
        'guest_code': guest_code, 'service_name': 'Bistro Lunch', 'amount': '25.50'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Welcome, Diana Day!' in response.data
    assert b'Hosted by' in response.data

    # Guest ledger holds the purchase
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT transaction_value FROM guest_activities WHERE guest_id = ? AND activity_type = 'purchase'", (guest['id'],))
    rows = cursor.fetchall()
    assert any(abs(r['transaction_value'] - 25.50) < 0.001 for r in rows)
    conn.close()

    # Host engagement score reflects the guest's spending
    summary = EngagementEngine.calculate_engagement_score(guest['host_member_id'])
    assert summary['guest_spending'] >= 25.50

def test_guest_quick_redirects_when_already_signed_in(client):
    # Sign in as a guest for today via the day-pass portal
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    client.post('/member/guest/create', data={'guest_name': 'Fiona Fast'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT guest_code FROM guest_ids WHERE guest_name = 'Fiona Fast' ORDER BY id DESC LIMIT 1")
    guest_code = cursor.fetchone()['guest_code']
    conn.close()
    client.post('/login', data={'guest_code': guest_code}, follow_redirects=True)

    # Already signed in today -> quick page bounces straight to the dashboard
    response = client.get('/guest/quick', follow_redirects=True)
    assert response.status_code == 200
    assert b'Guest Day Pass - Fiona Fast' in response.data

def test_login_invalid_tab_falls_back_to_account(client):
    # An invalid ?tab= value must not blank the login form — both panels hidden
    response = client.get('/login?tab=foo')
    assert response.status_code == 200
    assert b'Username' in response.data
    assert b'Guest Pass Code' in response.data

def test_member_login_clears_prior_guest_session(client):
    # Sign in as guest first, then as a member — member session must replace guest
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    client.post('/member/guest/create', data={'guest_name': 'Gina Swap'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT guest_code FROM guest_ids WHERE guest_name = 'Gina Swap' ORDER BY id DESC LIMIT 1")
    guest_code = cursor.fetchone()['guest_code']
    conn.close()
    client.post('/login', data={'guest_code': guest_code}, follow_redirects=True)

    # Now log in as a member — should land in the member suite, not the guest one
    response = client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Welcome back, alice!' in response.data
    assert b'Member Dashboard' in response.data
    assert b'Guest Day Pass' not in response.data

def test_guest_day_pass_expires_next_day(client):
    # Create pass and sign in as the guest
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    client.post('/member/guest/create', data={'guest_name': 'Eve Expire'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT guest_code FROM guest_ids WHERE guest_name = 'Eve Expire' ORDER BY id DESC LIMIT 1")
    guest_code = cursor.fetchone()['guest_code']
    conn.close()
    client.post('/login', data={'guest_code': guest_code}, follow_redirects=True)

    # Age the session to yesterday -> dashboard must bounce back to sign-in
    with client.session_transaction() as sess:
        sess['guest_login_date'] = '2000-01-01'

    response = client.get('/guest/dashboard', follow_redirects=True)
    assert b'day pass has expired' in response.data
    assert b'Member / Admin' in response.data
    assert b'Guest Pass Code' in response.data

def test_member_scan_checkin_checkout_flow(client):
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)

    # Scanner page renders facility barcodes
    response = client.get('/member/scan')
    assert response.status_code == 200
    assert b'Facility Barcode Scanner' in response.data
    assert b'FAC-101' in response.data

    # First scan: check in to facility (timer starts)
    response = client.post('/member/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
    assert b'Checked in to Club Fitness' in response.data
    assert b'Session Active' in response.data

    # Scanning a different facility while active -> warning, session stays active
    response = client.post('/member/scan', data={'facility_code': 'FAC-102'}, follow_redirects=True)
    assert b'currently checked into' in response.data
    assert b'Session Active' in response.data

    # Second scan of the same facility: check out and log duration
    response = client.post('/member/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
    assert b'Checked out of Club Fitness' in response.data
    assert b'Ready to Scan' in response.data

    # Unknown barcode rejected
    response = client.post('/member/scan', data={'facility_code': 'UNKNOWN'}, follow_redirects=True)
    assert b'Unknown facility barcode' in response.data

    # Session duration is recorded in history
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM facility_checkins WHERE status = 'completed'")
    assert cursor.fetchone()[0] >= 1
    conn.close()
