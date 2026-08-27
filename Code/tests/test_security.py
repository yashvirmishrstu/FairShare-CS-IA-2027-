import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from main import app
from database import init_db, get_db

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
    old = app.config.get('WTF_CSRF_ENABLED', True)
    app.config['WTF_CSRF_ENABLED'] = True
    with app.test_client() as client:
        yield client
    app.config['WTF_CSRF_ENABLED'] = old


@pytest.fixture
def client(db):
    old = app.config.get('WTF_CSRF_ENABLED', True)
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client
    app.config['WTF_CSRF_ENABLED'] = old


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


# ---- VULN-001: seeded credentials are never public defaults ---------------


def _fresh_db(tmp_path, monkeypatch, *, admin_password=None, seed_demo=None):
    """Seed a brand-new database under controlled env: None = variable unset."""
    monkeypatch.setattr('config.Config.DATABASE', str(tmp_path / 'fresh_sec.db'))
    if admin_password is None:
        monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    else:
        monkeypatch.setenv('ADMIN_PASSWORD', admin_password)
    if seed_demo is None:
        monkeypatch.delenv('SEED_DEMO_DATA', raising=False)
    else:
        monkeypatch.setenv('SEED_DEMO_DATA', seed_demo)
    init_db()


def test_admin_password_is_not_the_public_default(tmp_path, monkeypatch):
    """With no ADMIN_PASSWORD set, the old publicly-known 'admin123' must NOT
    verify — the seeded password is random, never a hardcoded value."""
    from werkzeug.security import check_password_hash
    _fresh_db(tmp_path, monkeypatch)  # no ADMIN_PASSWORD, no SEED_DEMO_DATA
    conn = get_db()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = 'admin'"
    ).fetchone()
    conn.close()
    assert row is not None, 'an admin account must still be created'
    assert check_password_hash(row['password_hash'], 'admin123') is False


def test_demo_members_absent_without_seed_demo_data(tmp_path, monkeypatch):
    """Demo members (documented passwords) must not exist by default."""
    _fresh_db(tmp_path, monkeypatch, admin_password='op-secret')
    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'member'"
    ).fetchone()[0]
    conn.close()
    assert n == 0


def test_admin_password_reads_from_environment(tmp_path, monkeypatch):
    """ADMIN_PASSWORD lets the operator choose the admin password; opting into
    SEED_DEMO_DATA restores the documented demo members."""
    from werkzeug.security import check_password_hash
    _fresh_db(tmp_path, monkeypatch, admin_password='s3cure-operator-pass', seed_demo='1')
    conn = get_db()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = 'admin'"
    ).fetchone()
    members = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'member'"
    ).fetchone()[0]
    conn.close()
    assert check_password_hash(row['password_hash'], 's3cure-operator-pass') is True
    assert check_password_hash(row['password_hash'], 'admin123') is False
    assert members == 4
