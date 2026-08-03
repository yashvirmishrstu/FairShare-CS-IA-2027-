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
    assert b'Sign In' in response.data
    assert b'Sign In' in response.data

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
    assert b'Sign In' in response.data
    assert b'Sign In' in response.data

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
    assert b'Sign In' in response.data

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
    assert b'Sign In' in response.data
    assert b'Sign In' in response.data

def test_admin_issues_receipt_and_member_scans(client):
    """Admin issues an expense receipt QR; member scans it to log the expense."""
    # Admin issues a receipt voucher
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    response = client.post('/admin/receipts/issue', data={
        'service_name': 'Restaurant Dining', 'amount': '42.75'
    }, follow_redirects=True)
    assert b'Receipt issued' in response.data

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM receipts WHERE service_name = 'Restaurant Dining' ORDER BY id DESC LIMIT 1")
    receipt = cursor.fetchone()
    conn.close()
    receipt_code = receipt['receipt_code']
    assert receipt_code.startswith('RCPT-')
    assert receipt['status'] == 'unscanned'

    # Member logs in and scans the receipt QR
    client.get('/logout')
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    response = client.post('/member/receipts/scan', data={'receipt_code': receipt_code}, follow_redirects=True)
    assert b'logged from receipt' in response.data
    assert b'Restaurant Dining' in response.data

    # Expense appears in the member's purchase ledger
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM activities a
        JOIN members m ON a.member_id = m.id
        WHERE m.full_name = 'Alice Johnson' AND a.activity_type = 'purchase' AND a.service_name = 'Restaurant Dining'
    ''')
    assert cursor.fetchone()[0] == 1
    # Receipt marked scanned
    cursor.execute("SELECT status FROM receipts WHERE id = ?", (receipt['id'],))
    assert cursor.fetchone()['status'] == 'scanned'
    conn.close()

    # Member expenses page renders with the ledger
    response = client.get('/member/expenses')
    assert response.status_code == 200
    assert b'Track Expenses by Receipt' in response.data
    assert receipt_code.encode() in response.data

def test_receipt_deduplication_and_validation(client):
    """A receipt QR can only be scanned once; invalid codes are rejected."""
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    client.post('/admin/receipts/issue', data={'service_name': 'Pro Shop', 'amount': '18.99'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT receipt_code FROM receipts WHERE service_name = 'Pro Shop' ORDER BY id DESC LIMIT 1")
    receipt_code = cursor.fetchone()['receipt_code']
    conn.close()

    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)

    # First scan succeeds
    response = client.post('/member/receipts/scan', data={'receipt_code': receipt_code}, follow_redirects=True)
    assert b'logged from receipt' in response.data

    # Second scan rejected (deduplication)
    response = client.post('/member/receipts/scan', data={'receipt_code': receipt_code}, follow_redirects=True)
    assert b'already been scanned' in response.data

    # Invalid code rejected
    response = client.post('/member/receipts/scan', data={'receipt_code': 'RCPT-NOPE'}, follow_redirects=True)
    assert b'Invalid receipt code' in response.data

    # Empty code -> warning
    response = client.post('/member/receipts/scan', data={'receipt_code': ''}, follow_redirects=True)
    assert b'No receipt QR detected' in response.data

def test_guest_scans_receipt_credits_host(client):
    """Guest scanning a receipt QR credits the expense to their host member."""
    # Alice creates a guest pass
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    client.post('/member/guest/create', data={'guest_name': 'Diana Day'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, guest_code, host_member_id FROM guest_ids WHERE guest_name = 'Diana Day' ORDER BY id DESC LIMIT 1")
    guest = cursor.fetchone()
    conn.close()

    # Admin issues a receipt
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    client.post('/admin/receipts/issue', data={'service_name': 'Spa Retreat', 'amount': '95.00'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT receipt_code FROM receipts WHERE service_name = 'Spa Retreat' ORDER BY id DESC LIMIT 1")
    receipt_code = cursor.fetchone()['receipt_code']
    conn.close()

    # Guest signs in and scans the receipt QR
    client.post('/login', data={'guest_code': guest['guest_code']}, follow_redirects=True)
    response = client.post('/guest/receipts/scan', data={'receipt_code': receipt_code}, follow_redirects=True)
    assert b'credited to your host member' in response.data

    # Guest ledger holds the purchase; host rewards reflect the guest spending
    summary = EngagementEngine.calculate_engagement_score(guest['host_member_id'])
    assert summary['guest_spending'] >= 95.00

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM guest_activities WHERE guest_id = ? AND activity_type = 'purchase' AND service_name = 'Spa Retreat'", (guest['id'],))
    assert cursor.fetchone()[0] == 1
    conn.close()

    # Guest dashboard renders the Scan Receipt QR card
    response = client.get('/guest/dashboard')
    assert response.status_code == 200
    assert b'Scan Receipt QR' in response.data

def test_receipt_cross_role_dedup_and_admin_validation(client):
    """A receipt scanned by a guest is then rejected for a member; admin
    issue route validates service name and amount."""
    # Admin issue validation: blank service rejected, non-positive amount rejected
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    response = client.post('/admin/receipts/issue', data={'service_name': '', 'amount': '10.00'}, follow_redirects=True)
    assert b'Please describe the service' in response.data
    response = client.post('/admin/receipts/issue', data={'service_name': 'Gift Shop', 'amount': '0.00'}, follow_redirects=True)
    assert b'greater than zero' in response.data
    response = client.post('/admin/receipts/issue', data={'service_name': 'Gift Shop', 'amount': '-5.00'}, follow_redirects=True)
    assert b'greater than zero' in response.data
    client.get('/logout')

    # Alice creates a guest pass and a receipt is issued
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    client.post('/member/guest/create', data={'guest_name': 'Cora Cross'}, follow_redirects=True)
    client.get('/logout')
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    client.post('/admin/receipts/issue', data={'service_name': 'Tennis Pro Shop', 'amount': '55.00'}, follow_redirects=True)
    client.get('/logout')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT receipt_code FROM receipts WHERE service_name = 'Tennis Pro Shop' ORDER BY id DESC LIMIT 1")
    receipt_code = cursor.fetchone()['receipt_code']
    cursor.execute("SELECT guest_code FROM guest_ids WHERE guest_name = 'Cora Cross' ORDER BY id DESC LIMIT 1")
    guest_code = cursor.fetchone()['guest_code']
    conn.close()

    # Guest scans it first
    client.post('/login', data={'guest_code': guest_code}, follow_redirects=True)
    response = client.post('/guest/receipts/scan', data={'receipt_code': receipt_code}, follow_redirects=True)
    assert b'credited to your host member' in response.data
    client.get('/logout')

    # Member attempting the same receipt is now rejected (cross-role dedup)
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    response = client.post('/member/receipts/scan', data={'receipt_code': receipt_code}, follow_redirects=True)
    assert b'already been scanned' in response.data

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
    assert b'Facility Barcode Scanner' in response.data

    # Unknown barcode rejected
    response = client.post('/member/scan', data={'facility_code': 'UNKNOWN'}, follow_redirects=True)
    assert b'Unknown facility barcode' in response.data

    # Session duration is recorded in history
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM facility_checkins WHERE status = 'completed'")
    assert cursor.fetchone()[0] >= 1
    conn.close()
