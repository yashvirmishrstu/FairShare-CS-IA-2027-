import pytest
import os
import re
from main import app
from database import init_db, get_db
from models import EngagementEngine, RewardSettings, MarketplaceManager

@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = os.path.join(tmp_path, "test_app_fairshare.db")
    monkeypatch.setattr('config.Config.DATABASE', test_db)
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False  # test client sends no CSRF token
    init_db()

    with app.test_client() as client:
        yield client

def test_home_page(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'FairShare' in response.data

def test_csrf_protection_active_and_token_present(client):
    """VULN-002: with CSRF enabled, a tokenless POST is rejected (HTTP 400)
    and the rendered login form carries a working csrf_token that the same
    session can submit successfully."""
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        resp = client.get('/login')
        assert resp.status_code == 200
        m = re.search(rb'name="csrf_token" value="([^"]+)"', resp.data)
        assert m is not None, "login form must render a csrf_token hidden input"
        token = m.group(1).decode()

        # A POST without the token is rejected before the route runs.
        rejected = client.post('/login', data={
            'username': 'alice', 'password': 'password123'
        })
        assert rejected.status_code == 400

        # The same POST with the rendered token succeeds.
        accepted = client.post('/login', data={
            'username': 'alice', 'password': 'password123', 'csrf_token': token
        }, follow_redirects=True)
        assert accepted.status_code == 200
        assert b'Welcome back, alice!' in accepted.data
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
        client.get('/logout')


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
    assert b'Total Points Earned' in rewards_csv.data

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

def test_member_marketplace_page_renders(client):
    """Member marketplace page shows spendable points, coupon catalog, and
    the yearly fee credit panel."""
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    response = client.get('/member/marketplace')
    assert response.status_code == 200
    assert b'Points Marketplace' in response.data
    assert b'Spendable Points' in response.data
    assert b'Coupon Catalog' in response.data
    assert b'Yearly Membership Fee' in response.data
    # Seeded demo coupons are listed
    assert b'Gym Day Pass' in response.data
    assert b'Claim for' in response.data


def test_member_marketplace_claim_flow(client):
    """Member claims a coupon from the marketplace — points are deducted and
    the coupon code appears in the My Coupons section."""
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()
    EngagementEngine.recalculate_all()
    coupon = MarketplaceManager.get_active_coupons()[0]

    response = client.post('/member/marketplace/claim', data={'coupon_id': coupon['id']}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Coupon claimed' in response.data

    # Coupon shows in My Coupons with its QR code
    claimed = MarketplaceManager.get_member_coupons(alice_id)
    assert len(claimed) == 1
    assert claimed[0]['coupon_code'] in response.data.decode()
    assert b'My Coupons' in response.data

    # Balance reduced
    rewards = EngagementEngine.view_member_rewards(alice_id)
    assert rewards['points_spent'] == coupon['cost_points']


def test_member_marketplace_fee_credit_flow(client):
    """Member credits points against the yearly fee from the marketplace."""
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()
    EngagementEngine.recalculate_all()

    response = client.post('/member/marketplace/fee', data={'points': '100'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'pts converted to' in response.data

    fee = MarketplaceManager.get_member_fee(alice_id)
    assert fee['fee_points_applied'] > 0
    assert fee['remaining'] < fee['yearly_fee']


def test_member_marketplace_rejects_overdraft(client):
    """Claiming an unaffordable coupon or over-crediting the fee is rejected."""
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()
    EngagementEngine.recalculate_all()

    # Drain Alice's balance via the ledger
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT engagement_score FROM rewards WHERE member_id = ?", (alice_id,))
    earned = cursor.fetchone()['engagement_score']
    cursor.execute("INSERT INTO point_transactions (member_id, points_delta, reason) VALUES (?, ?, ?)",
                   (alice_id, -earned, 'Test drain'))
    conn.commit()
    conn.close()

    coupon = MarketplaceManager.get_active_coupons()[0]
    response = client.post('/member/marketplace/claim', data={'coupon_id': coupon['id']}, follow_redirects=True)
    assert b'Insufficient points' in response.data

    response = client.post('/member/marketplace/fee', data={'points': '10'}, follow_redirects=True)
    assert b'points available' in response.data


def test_redeem_recreates_stable_voucher_and_preserves_marketplace_access(client):
    """Redeeming a voucher must create exactly one fresh active voucher that
    survives reloads, while coupon claims and fee credits still work after the
    old voucher is marked redeemed."""
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()

    # Materialize the initial voucher so this test exercises the actual
    # redeemed -> replacement transition rather than the first-ever creation.
    EngagementEngine.recalculate_all(force=True)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT redemption_code FROM rewards WHERE member_id = ? AND status = 'active'", (alice_id,))
    original_code = cursor.fetchone()['redemption_code']
    conn.close()

    response = client.get('/member/rewards')
    assert response.status_code == 200
    assert original_code.encode() in response.data

    # Redeem the active voucher. The route must persist a replacement row.
    response = client.post('/member/rewards', follow_redirects=True)
    assert response.status_code == 200
    # The flash text is HTML-escaped in the rendered page; assert its stable
    # unescaped prefix rather than coupling this test to template escaping.
    assert b'Voucher code generated' in response.data

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT redemption_code, status FROM rewards WHERE member_id = ? ORDER BY id", (alice_id,))
    reward_rows = cursor.fetchall()
    cursor.execute("SELECT redemption_code FROM rewards WHERE member_id = ? AND status = 'active'", (alice_id,))
    active_code = cursor.fetchone()['redemption_code']
    cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    pending = cursor.fetchone()['pending']
    conn.close()

    assert len(reward_rows) == 2
    assert [row['status'] for row in reward_rows] == ['redeemed', 'active']
    assert active_code != original_code
    assert pending == 0

    # Reloading must keep the exact persisted replacement code, not generate a
    # new code on every read.
    for reload_response in (client.get('/member/rewards'), client.get('/member/rewards')):
        assert reload_response.status_code == 200
        match = re.search(rb'data-qr="(FS-RED-[A-Z0-9]{16})"', reload_response.data)
        assert match is not None
        assert match.group(1).decode() == active_code

    # The member can still spend points after redeeming the old voucher.
    coupon = next(c for c in MarketplaceManager.get_active_coupons() if c['name'] == 'Gym Day Pass')
    response = client.post('/member/marketplace/claim', data={'coupon_id': coupon['id']}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Coupon claimed' in response.data

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM member_coupons WHERE member_id = ?", (alice_id,))
    assert cursor.fetchone()[0] == 1
    conn.close()

    # Fee credit must also continue to use the live earned score after redeem.
    response = client.post('/member/marketplace/fee', data={'points': '10'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'pts converted to' in response.data

    fee = MarketplaceManager.get_member_fee(alice_id)
    settings = RewardSettings.get_settings()
    assert fee['fee_points_applied'] == round(10 * settings['points_value_dollars'], 2)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT points_delta FROM point_transactions WHERE member_id = ? AND reason = 'Yearly membership fee credit'", (alice_id,))
    fee_transaction = cursor.fetchone()
    conn.close()
    assert fee_transaction is not None
    assert fee_transaction['points_delta'] == -10

    # Marketplace spending must not destroy the replacement voucher.
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards WHERE member_id = ? AND status = 'active'", (alice_id,))
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_admin_marketplace_manages_coupons(client):
    """Admin can add a coupon and toggle its availability."""
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)

    # Add a coupon
    response = client.post('/admin/marketplace', data={
        'action': 'add',
        'name': 'Yoga Class Pass',
        'description': 'One yoga class session in the wellness studio.',
        'category': 'Events',
        'cost_points': '45',
        'value_amount': '12',
        'facility_name': '',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Yoga Class Pass' in response.data
    assert b'added to the marketplace' in response.data

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM coupons WHERE name = 'Yoga Class Pass'")
    coupon = cursor.fetchone()
    conn.close()
    assert coupon is not None
    assert coupon['active'] == 1

    # Toggle it off
    response = client.post('/admin/marketplace', data={'action': 'toggle', 'coupon_id': coupon['id']}, follow_redirects=True)
    assert b'deactivated' in response.data

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT active FROM coupons WHERE id = ?", (coupon['id'],))
    assert cursor.fetchone()['active'] == 0
    conn.close()

    # No longer appears for members
    client.get('/logout')
    client.post('/login', data={'username': 'alice', 'password': 'password123'}, follow_redirects=True)
    response = client.get('/member/marketplace')
    assert b'Yoga Class Pass' not in response.data


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

def test_admin_member_edit_never_touches_membership_tier(client):
    """With the tier system removed, editing a member's contact details must
    NOT read or write membership_type — the tier column is dormant and must
    never be silently reset by partial form submissions."""
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''SELECT m.id FROM members m JOIN users u ON m.user_id = u.id WHERE u.username = 'alice' ''')
    alice_id = cursor.fetchone()['id']
    conn.close()

    # First edit submits membership_type='VIP' — the route ignores it.
    response = client.post(f'/admin/members/edit/{alice_id}', data={
        'full_name': 'Alice Johnson', 'email': 'alice@example.com', 'phone': '555-0101',
        'membership_type': 'VIP'
    }, follow_redirects=True)
    assert b'Member record updated' in response.data

    # Second edit omits membership_type entirely — still no reset.
    response = client.post(f'/admin/members/edit/{alice_id}', data={
        'full_name': 'Alice Johnson', 'email': 'alice@example.com', 'phone': '555-9999'
    }, follow_redirects=True)
    assert b'Member record updated' in response.data

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT membership_type FROM members WHERE id = ?", (alice_id,))
    tier = cursor.fetchone()['membership_type']
    conn.close()
    assert tier == 'Member'

    # The tier multiplier is hardcoded to 1.0 regardless of tier column.
    summary = EngagementEngine.calculate_engagement_score(alice_id)
    assert summary['tier_multiplier'] == 1.0

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


def test_login_locks_out_after_repeated_failures(client):
    """VULN-003: after the failure threshold the account is locked — even a
    correct password is rejected while the lock window is active."""
    from models import LoginThrottle

    # Stay under the threshold first: 3 failures still allow a correct login.
    for _ in range(3):
        client.post('/login', data={'username': 'alice', 'password': 'wrongpass'})
    ok = client.post('/login', data={'username': 'alice', 'password': 'password123'},
                     follow_redirects=True)
    assert b'Welcome back, alice!' in ok.data

    # Now exceed the threshold: 5 more failures lock the account.
    for _ in range(5):
        client.post('/login', data={'username': 'alice', 'password': 'wrongpass'})
    locked = client.post('/login', data={'username': 'alice', 'password': 'password123'},
                         follow_redirects=True)
    assert b'Too many failed login attempts' in locked.data
    assert b'Welcome back, alice!' not in locked.data
    assert LoginThrottle.is_locked('alice') > 0


def test_login_lock_clears_on_success(client):
    """A successful login resets the failure counter, so a member who then
    mistypes a few times is not locked out by an old streak."""
    from models import LoginThrottle

    for _ in range(3):
        client.post('/login', data={'username': 'alice', 'password': 'wrongpass'})
    ok = client.post('/login', data={'username': 'alice', 'password': 'password123'},
                     follow_redirects=True)
    assert b'Welcome back, alice!' in ok.data
    assert LoginThrottle.is_locked('alice') == 0

    # 3 more failures stay under the threshold (counter was reset to zero).
    for _ in range(3):
        client.post('/login', data={'username': 'alice', 'password': 'wrongpass'})
    ok2 = client.post('/login', data={'username': 'alice', 'password': 'password123'},
                      follow_redirects=True)
    assert b'Welcome back, alice!' in ok2.data


def test_guest_code_login_is_rate_limited(client):
    """Repeatedly failing a guest-code sign-in locks that code out too."""
    for _ in range(6):
        response = client.post('/login', data={'guest_code': 'GST-BADCODE'},
                               follow_redirects=True)
    assert b'Too many failed login attempts' in response.data


def test_guest_quick_route_cannot_bypass_throttle(client):
    """The /guest/quick check-in path accepts guest codes too, so it must
    enforce the same exponential-backoff lockout — otherwise it would be an
    unbounded brute-force vector for guessing guest pass codes."""
    from models import LoginThrottle

    # A code that doesn't exist yet, so every attempt fails and counts up.
    bad_code = 'GST-NEVER4'
    for _ in range(5):
        response = client.post('/guest/quick', data={
            'guest_code': bad_code,
            'service_name': 'Bistro & Lounge',
            'amount': '25.00',
        }, follow_redirects=True)
        assert b'Invalid Guest Pass Code' in response.data

    # The 7th attempt is refused outright — locked, no further lookups.
    locked = client.post('/guest/quick', data={
        'guest_code': bad_code,
        'service_name': 'Bistro & Lounge',
        'amount': '25.00',
    }, follow_redirects=True)
    assert b'Too many failed login attempts' in locked.data
    assert LoginThrottle.is_locked(bad_code) > 0

    # A successful code still works afterwards (the throttle is per-code).
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()
    from models import GuestManager
    guest = GuestManager.create_guest_id(alice_id, "Quick Throttle Guest")
    ok = client.post('/guest/quick', data={
        'guest_code': guest['guest_code'],
        'service_name': 'Bistro & Lounge',
        'amount': '25.00',
    }, follow_redirects=True)
    assert b'Welcome,' in ok.data
