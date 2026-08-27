"""
================================================================================
 FAIRSHARE — VERCEL_URL SMOKE TEST (boots the app through the Turso adapter)
================================================================================
 Boots the FULL Flask app with the hosted-SQLite (Turso/libSQL) adapter wired
 in, then drives the KEY routes exactly as a visitor would: unauthenticated
 pages, member login + dashboard, facility scanning, rewards, coupon claim,
 the guest day-pass flow, and the admin suite. Every request's database
 access goes through database._TursoConnection, so a green run proves the
 deployed persistence stack (libSQL/Hrana) works end-to-end.

 Usage (run in CI or locally against a sqld server):
     set TURSO_URL=ws://127.0.0.1:8081        (local sqld, or libsql://...)
     set TURSO_AUTH_TOKEN=<token>             (only for hosted Turso)
     set ADMIN_PASSWORD=admin123
     set SEED_DEMO_DATA=1                     (documented demo accounts)
     set SECRET_KEY=anything
     python smoke_vercel.py

 Optionally set VERCEL_URL=https://<project>.vercel.app to ALSO smoke-test
 the live deployed site's public routes over plain HTTP after the local boot
 checks pass. Exits non-zero on the first failed check.
"""
import os
import sys
import time
import urllib.request

os.environ.setdefault('SECRET_KEY', 'smoke-test')
os.environ.setdefault('ADMIN_PASSWORD', 'admin123')
os.environ.setdefault('SEED_DEMO_DATA', '1')
if not os.environ.get('TURSO_URL'):
    print('ERROR: TURSO_URL is required (e.g. ws://127.0.0.1:8081).', file=sys.stderr)
    sys.exit(2)

from main import app  # noqa: E402
import database  # noqa: E402
from models import GuestManager  # noqa: E402

app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False  # headless smoke test

FAILURES = []
TOTAL = 0


def check(name, cond, extra=''):
    global TOTAL
    TOTAL += 1
    print(('  PASS  ' if cond else '  FAIL  ') + name + (f'  ({extra})' if extra else ''))
    if not cond:
        FAILURES.append(name)


def body_has(resp, text):
    return text.lower() in resp.get_data(as_text=True).lower()


def main():
    # ---- boot: full schema + seeds THROUGH the Turso adapter ---------------
    database.init_db()
    check('boot: init_db through the Turso adapter', True)

    conn = database.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM members WHERE member_code = 'MBR-1001'")
    alice_id = cur.fetchone()['id']
    # Idempotent top-up so the coupon claim below always has enough points.
    cur.execute("INSERT INTO point_transactions (member_id, points_delta, reason) "
                "VALUES (?, 5000, 'smoke test top-up')", (alice_id,))
    conn.commit()
    cur.execute("SELECT id FROM coupons WHERE active = 1 ORDER BY cost_points LIMIT 1")
    coupon_id = cur.fetchone()['id']
    conn.close()

    # ---- public / unauthenticated routes -----------------------------------
    c = app.test_client()
    r = c.get('/')
    check('GET / (index)', r.status_code == 200)
    r = c.get('/login')
    check('GET /login', r.status_code == 200)
    r = c.get('/static/css/styles.css')
    check('GET /static/css/styles.css', r.status_code == 200 and len(r.data) > 1000)

    # ---- member flow --------------------------------------------------------
    m = app.test_client()
    r = m.post('/login', data={'username': 'alice', 'password': 'password123'},
               follow_redirects=True)
    check('member login (alice)', r.status_code == 200 and body_has(r, 'Alice'))
    r = m.get('/member/dashboard')
    check('GET /member/dashboard', r.status_code == 200 and body_has(r, 'Alice'))
    r = m.post('/member/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
    check('facility check-in', r.status_code == 200)
    r = m.post('/member/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
    check('facility check-out', r.status_code == 200)
    r = m.get('/member/rewards')
    check('GET /member/rewards', r.status_code == 200)
    r = m.get('/member/marketplace')
    check('GET /member/marketplace', r.status_code == 200)
    r = m.post('/member/marketplace/claim', data={'coupon_id': str(coupon_id)},
               follow_redirects=True)
    check('POST /member/marketplace/claim', r.status_code == 200)

    # ---- guest day-pass flow ------------------------------------------------
    guest = GuestManager.create_guest_id(alice_id, 'Smoke Test Guest')
    g = app.test_client()
    r = g.post('/login', data={'guest_code': guest['guest_code']}, follow_redirects=True)
    check('guest sign-in via pass code', r.status_code == 200 and body_has(r, 'Smoke Test Guest'))
    r = g.post('/guest/spending', data={'service_name': 'Bistro & Lounge', 'amount': '12.50'},
               follow_redirects=True)
    check('POST /guest/spending', r.status_code == 200)
    r = g.get('/guest/dashboard')
    check('GET /guest/dashboard', r.status_code == 200)
    r = c.get(f"/guest/pass/{guest['guest_code']}")
    check('GET /guest/pass/<code> (public share page)', r.status_code == 200)

    # ---- admin flow ----------------------------------------------------------
    a = app.test_client()
    r = a.post('/login', data={'username': 'admin', 'password': 'admin123'},
               follow_redirects=True)
    check('admin login', r.status_code == 200)
    r = a.get('/admin/dashboard')
    check('GET /admin/dashboard', r.status_code == 200)
    r = a.get('/admin/marketplace')
    check('GET /admin/marketplace', r.status_code == 200)

    # ---- live deployed site (optional VERCEL_URL) ----------------------------
    url = os.environ.get('VERCEL_URL', '').strip().rstrip('/')
    if url:
        for path in ('/login', '/static/css/styles.css', '/'):
            ok = False
            for _ in range(5):
                try:
                    with urllib.request.urlopen(url + path, timeout=20) as resp:
                        ok = resp.status in (200, 301, 302)
                    if ok:
                        break
                except Exception:
                    time.sleep(5)
            check(f'LIVE {url}{path}', ok)
    else:
        print('  (VERCEL_URL not set - skipping live-site HTTP checks)')

    print(f"\n===== SMOKE RESULT: {TOTAL - len(FAILURES)}/{TOTAL} checks passed =====")
    if FAILURES:
        print('FAILED:', FAILURES)
        return 1
    print('SMOKE TEST PASSED - app boots and key routes work through the Turso adapter')
    return 0


if __name__ == '__main__':
    sys.exit(main())
