import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from main import app
from database import init_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path, monkeypatch):
    test_db = os.path.join(tmp_path, "test_security_fairshare.db")
    monkeypatch.setattr('config.Config.DATABASE', test_db)
    app.config['TESTING'] = True
    init_db()
    yield


@pytest.fixture
def csrf_client(db):
    app.config['WTF_CSRF_ENABLED'] = True
    with app.test_client() as client:
        yield client
    app.config['WTF_CSRF_ENABLED'] = False


@pytest.fixture
def client(db):
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client


# ---- VULN-001: SECRET_KEY fail-closed ------------------------------------

def _run_config_import(env_overrides):
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, "-c", "import config"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), env=env,
    )
    return proc.returncode, proc.stderr


def test_secret_key_fails_closed_when_unset():
    code, err = _run_config_import({"SECRET_KEY": ""})
    assert code != 0, "config must refuse to import without SECRET_KEY"
    assert "SECRET_KEY is not set" in err


def test_secret_key_rejects_legacy_public_default():
    code, err = _run_config_import(
        {"SECRET_KEY": "fairshare_production_secret_key_2026"}
    )
    assert code != 0, "the legacy public default key must be rejected"
    assert "publicly-known default" in err


def test_secret_key_source_has_no_fallback_literal():
    src = (PROJECT_ROOT / "config.py").read_text(encoding="utf-8")
    m = re.search(r"SECRET_KEY\s*=\s*([^\r\n]+)", src)
    assert m is not None, "SECRET_KEY assignment not found in config.py"
    assignment = m.group(1)
    assert "os.environ.get('SECRET_KEY')" in assignment
    assert " or " not in assignment,         f"SECRET_KEY assignment must have no fallback value: {assignment.strip()}"


def test_secret_key_is_used_as_configured():
    import config
    assert config.Config.SECRET_KEY == os.environ.get('SECRET_KEY')
    assert app.config['WTF_CSRF_ENABLED'] is True


# ---- VULN-002: every POST route rejects tokenless CSRF --------------------

def _post_routes():
    """Enumerate POST-capable routes with concrete URLs from the URL map.
    Path parameters (e.g. <int:checkin_id>) are replaced with a dummy
    value directly in the pattern string since url_for needs a request
    context to build them. CSRF validation runs before the route body,
    so the dummy value never reaches the handler."""
    routes = []
    import re as _re
    for rule in app.url_map.iter_rules():
        if 'POST' not in rule.methods:
            continue
        url = _re.sub(r'<[^>]+>', '1', rule.rule)
        routes.append((rule.endpoint, rule.rule, url))
    return routes


def test_all_post_routes_reject_missing_csrf_token(csrf_client):
    rejected = []
    for endpoint, rule, url in _post_routes():
        resp = csrf_client.post(url, data={})
        if resp.status_code != 400:
            rejected.append((rule, endpoint, resp.status_code))
    assert not rejected,         "the following POST routes did NOT reject a tokenless request:\n" +         "\n".join(f"  {r} -> {e} (HTTP {s})" for r, e, s in rejected)


def test_csrf_still_allows_tokenised_request(csrf_client):
    resp = csrf_client.get('/login')
    assert resp.status_code == 200
    m = re.search(rb'name="csrf_token" value="([^"]+)"', resp.data)
    assert m is not None, "login form must render a csrf_token hidden input"
    token = m.group(1).decode()

    rejected = csrf_client.post('/login', data={
        'username': 'alice', 'password': 'password123'
    })
    assert rejected.status_code == 400

    accepted = csrf_client.post('/login', data={
        'username': 'alice', 'password': 'password123', 'csrf_token': token
    }, follow_redirects=True)
    assert accepted.status_code == 200
    assert b'Welcome back, alice!' in accepted.data


# ---- Cache hardening: /member/* pages must be no-store --------------------

MEMBER_PAGES = [
    '/member/dashboard',
    '/member/activity',
    '/member/expenses',
    '/member/scan',
    '/member/rewards',
    '/member/marketplace',
]


def test_member_pages_are_no_store(client):
    client.post('/login', data={
        'username': 'alice', 'password': 'password123'
    })
    for path in MEMBER_PAGES:
        resp = client.get(path)
        assert resp.status_code == 200, f'{path} should render for alice'
        cc = resp.headers.get('Cache-Control', '')
        assert 'no-store' in cc,             f'{path} Cache-Control is "{cc}" --- must include no-store'
        assert 'no-cache' in cc,             f'{path} Cache-Control is "{cc}" --- must include no-cache'


def test_member_pages_no_store_even_when_logged_out(client):
    resp = client.get('/member/dashboard')
    cc = resp.headers.get('Cache-Control', '')
    assert 'no-store' in cc,         f'/member/dashboard (logged out) Cache-Control is "{cc}"'


def test_static_assets_are_cacheable_but_pages_are_not(client):
    if app.debug:
        pytest.skip('debug mode never caches anything')
    resp = client.get('/static/css/styles.css')
    assert resp.status_code == 200
    assert 'public' in resp.headers.get('Cache-Control', '')

    resp = client.get('/login')
    cc = resp.headers.get('Cache-Control', '')
    assert 'no-store' in cc,         f'/login Cache-Control is "{cc}" --- pages must be no-store'
