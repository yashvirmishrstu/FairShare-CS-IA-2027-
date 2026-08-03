import pytest
import os
from main import app
from database import init_db, get_db

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
