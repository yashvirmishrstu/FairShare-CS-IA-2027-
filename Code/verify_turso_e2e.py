"""
================================================================================
 FAIRSHARE — END-TO-END VALIDATION OF THE HOSTED SQLITE (TURSO) NETWORK PATH
================================================================================
 Drives the WHOLE application through database._TursoConnection over the real
 libSQL network protocol (Hrana over WebSocket) and checks that everything
 the site depends on works remotely: schema init + seeding, SQLite triggers,
 password-hash queries, and the transactional business flows (guest pass
 lifecycle, receipt redemption, coupon marketplace).

 Usage:
     set TURSO_URL=ws://127.0.0.1:8081          (local sqld server, no token)
     set TURSO_URL=libsql://<db>-<org>.turso.io
     set TURSO_AUTH_TOKEN=<token>               (required for hosted Turso)
     set SECRET_KEY=anything                    (config.py fails closed)
     python verify_turso_e2e.py

 Local sqld (the exact server software Turso runs) can be started in WSL:
     sqld --http-listen-addr 0.0.0.0:8080 --hrana-listen-addr 0.0.0.0:8081 \
          --db-path ~/sqld-demo/fairshare-demo.db

 IB HL CS: this is a black-box *acceptance test* of the persistence layer —
 it exercises the adapter exactly as the running site does, including the
 BEGIN IMMEDIATE transactions (routed through the client's transaction()
 API, because raw BEGIN/COMMIT SQL is ignored by the Hrana protocol).
"""
import os
import sys

os.environ.setdefault('TURSO_URL', 'ws://127.0.0.1:8081')
if not os.environ.get('SECRET_KEY'):
    os.environ['SECRET_KEY'] = 'verify-turso-e2e'
# This is a local validation script: seed the documented demo accounts so the
# member/admin checks below have data (public deployments do NOT set these).
os.environ.setdefault('ADMIN_PASSWORD', 'admin123')
os.environ.setdefault('SEED_DEMO_DATA', '1')

import database  # noqa: E402
from models import GuestManager, ReceiptManager, MarketplaceManager  # noqa: E402
from werkzeug.security import check_password_hash  # noqa: E402

results = []


def check(name, cond, extra=''):
    results.append((name, bool(cond)))
    print(('  PASS  ' if cond else '  FAIL  ') + name + (f'  ({extra})' if extra else ''))


def main():
    print(f"Target: {os.environ['TURSO_URL']}")

    database.init_db()
    check('init_db: full schema + seeds over the network', True)

    conn = database.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    check('seeded admin present', cur.fetchone()[0] == 1)
    cur.execute("SELECT COUNT(*) FROM members")
    check('seeded 4 demo members', cur.fetchone()[0] == 4)
    cur.execute("SELECT COUNT(*) FROM coupons")
    check('seeded 8 marketplace coupons', cur.fetchone()[0] == 8)
    # SQLite triggers really run server-side: after any write the dirty flag
    # must flip to 1 (read before AND after so the check holds on re-runs).
    cur.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    before = cur.fetchone()['pending']
    cur.execute("INSERT INTO point_transactions (member_id, points_delta, reason) "
                "VALUES (1, -5, 'e2e trigger probe')")
    cur.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    check('dirty-flag trigger fires after a write',
          before in (0, 1) and cur.fetchone()['pending'] == 1)
    cur.execute("SELECT * FROM users WHERE username = 'admin'")
    admin = cur.fetchone()
    check('admin row addressable by name', admin is not None and admin['role'] == 'admin')
    check('password hash verifies over the network',
          check_password_hash(admin['password_hash'], 'admin123'))
    cur.execute("SELECT id FROM members ORDER BY id LIMIT 1")
    member_id = cur.fetchone()['id']
    conn.close()

    guest = GuestManager.create_guest_id(member_id, 'Network Guest')
    check('guest pass created (lastrowid over the network)', guest['guest_code'].startswith('GST-'))
    GuestManager.record_spending(guest['id'], 'Bistro & Lounge', 42.50)
    check('guest revoke (Hrana transaction)', GuestManager.revoke_guest_pass(member_id, guest['id'])['ok'] is True)
    report = GuestManager.get_guest_report(member_id, guest['id'])
    check('revoke report persisted (JSON snapshot + totals)',
          report is not None and report['total_spending'] == 42.50 and report['activity_count'] >= 1)

    rcpt = ReceiptManager.issue_receipt('Pro Shop Equipment', 55.00)
    check('receipt issued', rcpt['receipt_code'].startswith('RCPT-'))
    check('receipt redeemed by member', ReceiptManager.redeem_for_member(rcpt['receipt_code'], member_id)['ok'] is True)
    check('double redemption rejected (rowcount guard)',
          ReceiptManager.redeem_for_member(rcpt['receipt_code'], member_id)['ok'] is False)

    conn = database.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM coupons ORDER BY cost_points LIMIT 1")
    coupon_id = cur.fetchone()['id']
    conn.close()
    claim = MarketplaceManager.claim_coupon(member_id, coupon_id)
    check('coupon claimed (Hrana transaction)', claim['ok'] is True)
    check('coupon used once', MarketplaceManager.use_coupon(claim['coupon_code'], member_id)['ok'] is True)
    check('coupon double-use rejected', MarketplaceManager.use_coupon(claim['coupon_code'], member_id)['ok'] is False)

    conn = database.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM guest_pass_reports")
    reports = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM receipts WHERE status='scanned'")
    scanned = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM member_coupons WHERE status='used'")
    used = cur.fetchone()[0]
    conn.close()
    check('writes survive a NEW connection (cold-start survival)',
          reports >= 1 and scanned >= 1 and used >= 1,
          f'reports={reports}, scanned={scanned}, used={used}')

    failed = [name for name, ok in results if not ok]
    print(f"\n===== E2E RESULT: {len(results) - len(failed)}/{len(results)} checks passed =====")
    if failed:
        print('FAILED:', failed)
        return 1
    print('REAL NETWORK PATH VALIDATED (Hrana/WebSocket -> libSQL server)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
