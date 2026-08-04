"""
=============================================================================
 HEALTH-CHECK TESTS - endpoint resolution + full-page render sweep
=============================================================================
 These tests move the stale-server / typo regression checks from the live
 site into the test suite, so a broken url_for endpoint (BuildError) fails
 `pytest` instead of the running application.

 Two layers of defence:

  1. STATIC ENDPOINT SCAN
     Reuses check_endpoints.static_check(): scans every Jinja template and
     main.py for url_for('...') references and verifies each endpoint is
     registered in the fresh app's URL map. Catches typos and routes that
     were added to a template but never defined - the code-level form of
     the BuildError that crashed the marketplace when a stale server was
     running.

  2. FULL-PAGE RENDER SWEEP
     Logs in as a real member (alice) and as the admin, then GETs every
     page in both suites and asserts a 200 with no error markers
     (BuildError / Traceback / Internal Server Error). Renders the actual
     templates through the Flask test client, so a template that calls a
     missing endpoint fails here - instantly, with no server needed.

 The CSV exports and the Chart.js analytics JSON endpoint are swept too.

 IB HL CS: verification & validation - static analysis (endpoint scan)
 plus integration testing (rendering every page through the app), the same
 pairing a CI pipeline uses to catch configuration drift.
"""
import json
import os

import pytest

from main import app
from database import init_db

# Endpoint names referenced by templates must exist in the URL map.
# These live at the project root, next to the tests directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Suites to render. Member pages require an alice session; admin pages
# require the admin session.
MEMBER_PAGES = [
    '/member/dashboard',
    '/member/activity',
    '/member/scan',
    '/member/expenses',
    '/member/rewards',
    '/member/marketplace',
    '/member/coupon/redeem',
]

ADMIN_PAGES = [
    '/admin/dashboard',
    '/admin/members',
    '/admin/activity',
    '/admin/marketplace',
    '/admin/settings',
    '/admin/reports',
]

# Error signatures that must never appear in a rendered page body.
ERROR_MARKERS = [b'BuildError', b'Traceback (most recent call last)', b'Internal Server Error']


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh temp DB + Flask test client (same pattern as test_app.py)."""
    test_db = os.path.join(tmp_path, 'test_health_fairshare.db')
    monkeypatch.setattr('config.Config.DATABASE', test_db)
    app.config['TESTING'] = True
    init_db()
    with app.test_client() as client:
        yield client


def _login(client, username, password):
    """Log in and follow the redirect so the session is established."""
    response = client.post('/login', data={'username': username, 'password': password},
                           follow_redirects=True)
    assert response.status_code == 200
    return response


# ---------------------------------------------------------------------------
# 1. STATIC ENDPOINT SCAN
# ---------------------------------------------------------------------------

def test_all_url_for_endpoints_resolve():
    """Every url_for endpoint referenced in templates/main.py must exist in
    the app's URL map — the code-level guard against BuildError."""
    import sys
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    import check_endpoints

    missing = check_endpoints.static_check()
    assert not missing, (
        f"{len(missing)} url_for reference(s) point to missing endpoints:\n" +
        "\n".join(f"  {rel}:{line} -> url_for('{endpoint}')" for rel, line, endpoint in missing)
    )


# ---------------------------------------------------------------------------
# 2. FULL-PAGE RENDER SWEEP
# ---------------------------------------------------------------------------

def test_member_suite_renders(client):
    """Every member page renders 200 with no error markers."""
    _login(client, 'alice', 'password123')
    for page in MEMBER_PAGES:
        response = client.get(page)
        assert response.status_code == 200, f'{page} returned {response.status_code}'
        for marker in ERROR_MARKERS:
            assert marker not in response.data, f'{page} contains {marker.decode()}'


def test_admin_suite_renders(client):
    """Every admin page renders 200 with no error markers."""
    _login(client, 'admin', 'admin123')
    for page in ADMIN_PAGES:
        response = client.get(page)
        assert response.status_code == 200, f'{page} returned {response.status_code}'
        for marker in ERROR_MARKERS:
            assert marker not in response.data, f'{page} contains {marker.decode()}'


def test_admin_analytics_json_and_csv_exports(client):
    """The admin analytics JSON endpoint and both CSV exports answer 200
    with their expected content types and no error markers."""
    _login(client, 'admin', 'admin123')

    # Analytics JSON feeding the Chart.js dashboards
    response = client.get('/admin/api/analytics')
    assert response.status_code == 200
    assert response.mimetype == 'application/json'
    data = json.loads(response.data)
    assert 'facility_trends' in data
    assert 'reward_distribution' in data
    assert 'peak_hours' in data

    # CSV exports
    usage = client.get('/admin/reports/export/usage_csv')
    assert usage.status_code == 200
    assert usage.mimetype == 'text/csv'
    assert b'Member Code' in usage.data

    rewards = client.get('/admin/reports/export/rewards_csv')
    assert rewards.status_code == 200
    assert rewards.mimetype == 'text/csv'
    assert b'Total Points Earned' in rewards.data
