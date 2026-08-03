"""Headless behavioral verification of FairShare's real logic.

Drives the actual Flask app + models against a FRESH seeded database and
ASSERTS every state transition in the full member/guest lifecycle:
  member earns (facility, purchase, referral) -> claims coupon -> fee credit
  -> voucher redeem -> guest boards/pays/leaves credits host -> dedup.
Exits non-zero if any assertion fails.
"""
import os
import sys
import tempfile
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Point the app at a throwaway DB BEFORE anything imports it.
import config
TMPDIR = tempfile.mkdtemp(prefix="fairshare_verify_")
config.Config.DATABASE = os.path.join(TMPDIR, "verify.db")

from database import init_db, get_db
from models import EngagementEngine, MarketplaceManager
init_db()

from main import app
app.config['TESTING'] = True

FAILURES = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILURES.append(msg)


def login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def logout(client):
    client.get('/logout')


def member_id_of(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT m.id FROM members m JOIN users u ON m.user_id=u.id WHERE u.username=?", (username,))
    mid = cur.fetchone()['id']
    conn.close()
    return mid


def db_rows(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def db_one(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return row


# ============================================================
# 1. MEMBER EARN LIFECYCLE (facility check-in/out + receipt)
# ============================================================
c = app.test_client()
alice_id = member_id_of('alice')
resp = login(c, 'alice', 'password123')
check(b'Welcome back, alice!' in resp.data, "alice logs in to member dashboard")

base = EngagementEngine.calculate_engagement_score(alice_id)
check(base['visit_count'] == 1 and base['direct_spending'] == 180.50 and base['guest_referrals'] == 2,
      "seed baseline: 1 visit, $180.50 spending, 2 referrals")

# Facility: check in, then check out -> visit + facility minutes
r = c.post('/member/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
check(b'Checked in to Club Fitness' in r.data, "member checks in to Club Fitness")
r = c.post('/member/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
check(b'Checked out of Club Fitness' in r.data, "member checks out (session completed)")

after_facility = EngagementEngine.calculate_engagement_score(alice_id)
check(after_facility['visit_count'] == base['visit_count'] + 1, "check-in/out logged a second visit")
check(after_facility['facility_minutes'] >= 1, "facility minutes recorded (%s)" % after_facility['facility_minutes'])
check(after_facility['engagement_score'] > base['engagement_score'],
      "engagement score grew after facility session")
check(db_one("SELECT COUNT(*) c FROM facility_checkins WHERE status='completed'")['c'] >= 1,
      "facility checkin row completed in DB")

# Receipt scan: admin issues, member scans -> purchase logged + points
c2 = app.test_client()
login(c2, 'admin', 'admin123')
r = c2.post('/admin/receipts/issue', data={'service_name': 'Verification Dining', 'amount': '60.00'},
            follow_redirects=True)
check(b'Receipt issued' in r.data, "admin issues a receipt QR")
receipt_code = db_one("SELECT receipt_code FROM receipts WHERE service_name='Verification Dining' ORDER BY id DESC LIMIT 1")['receipt_code']
logout(c2)

r = c.post('/member/receipts/scan', data={'receipt_code': receipt_code}, follow_redirects=True)
check(b'logged from receipt' in r.data, "member scans receipt -> expense logged")
after_receipt = EngagementEngine.calculate_engagement_score(alice_id)
check(round(after_receipt['direct_spending'] - after_facility['direct_spending'], 2) == 60.00,
      "receipt purchase added $60 to direct spending")
check(db_one("SELECT status FROM receipts WHERE receipt_code=?", (receipt_code,))['status'] == 'scanned',
      "receipt marked scanned")

# Dedup: second scan rejected
r = c.post('/member/receipts/scan', data={'receipt_code': receipt_code}, follow_redirects=True)
check(b'already been scanned' in r.data, "receipt cannot be scanned twice (dedup)")

# ============================================================
# 2. MARKETPLACE: claim coupon -> points deducted + code issued
# ============================================================
EngagementEngine.recalculate_all()
before = EngagementEngine.view_member_rewards(alice_id)
coupon = next(cp for cp in MarketplaceManager.get_active_coupons() if cp['name'] == 'Gym Day Pass')

r = c.post('/member/marketplace/claim', data={'coupon_id': coupon['id']}, follow_redirects=True)
check(b'Coupon claimed' in r.data, "member claims Gym Day Pass coupon")
claimed = MarketplaceManager.get_member_coupons(alice_id)
check(len(claimed) == 1 and claimed[0]['coupon_code'].startswith('CPN-'), "coupon row + unique CPN- code issued")

after_claim = EngagementEngine.view_member_rewards(alice_id)
check(round(after_claim['points_balance'], 2) == round(before['points_balance'] - coupon['cost_points'], 2),
      "balance dropped by 40 pts: %s -> %s" % (before['points_balance'], after_claim['points_balance']))
check(round(after_claim['points_spent'], 2) == 40.0, "points_spent ledger = 40")
ledger = MarketplaceManager.get_point_transactions(alice_id)
check(ledger and ledger[0]['points_delta'] == -coupon['cost_points'], "point_transactions ledger records -40")

# Balance identity: balance == earned - spent, never negative
check(after_claim['points_balance'] == round(after_claim['engagement_score'] - after_claim['points_spent'], 2),
      "points_balance == engagement_score - points_spent")

# ============================================================
# 3. FEE CREDIT: points convert to dollars against yearly fee
# ============================================================
r = c.post('/member/marketplace/fee', data={'points': '100'}, follow_redirects=True)
check(b'pts converted to' in r.data, "member credits 100 pts toward yearly fee")
fee = MarketplaceManager.get_member_fee(alice_id)
rate = fee['points_value_dollars']
check(round(fee['fee_points_applied'], 2) == 50.00, "fee_points_applied = $50 (100 pts x %s)" % rate)
check(round(fee['remaining'], 2) == round(1200.00 - 50.00, 2), "fee remaining = $1150 (%s)" % fee['remaining'])
check(round(EngagementEngine.view_member_rewards(alice_id)['points_spent'], 2) == 140.0,
      "points_spent now 140 (40 coupon + 100 fee)")

# Overdraft: drain balance, claim must fail and fee credit must fail
earned = EngagementEngine.calculate_engagement_score(alice_id)['engagement_score']
conn = get_db()
conn.execute("INSERT INTO point_transactions (member_id, points_delta, reason) VALUES (?, ?, ?)",
             (alice_id, -earned, 'Verify drain'))
conn.commit()
conn.close()
r = c.post('/member/marketplace/claim', data={'coupon_id': coupon['id']}, follow_redirects=True)
check(b'Insufficient points' in r.data, "coupon claim rejected on overdraft")
r = c.post('/member/marketplace/fee', data={'points': '10'}, follow_redirects=True)
check(b'points available' in r.data, "fee credit rejected on overdraft")

# ============================================================
# 4. VOUCHER REDEEM: active -> redeemed -> NEW stable active code
# ============================================================
r = c.get('/member/rewards')
m = re.search(rb'data-qr="(FS-RED-[A-Z0-9]{8})"', r.data)
check(m is not None, "rewards page renders a QR redemption code")
original_code = m.group(1).decode()

r = c.post('/member/rewards', follow_redirects=True)
check(b'Voucher code generated' in r.data, "redeem action generates a fresh voucher")

rows = db_rows("SELECT redemption_code, status FROM rewards WHERE member_id=? ORDER BY id", (alice_id,))
check(len(rows) == 2 and [x['status'] for x in rows] == ['redeemed', 'active'],
      "reward rows: old redeemed + one new active (no dupes)")
active_code = db_one("SELECT redemption_code FROM rewards WHERE member_id=? AND status='active'", (alice_id,))['redemption_code']
check(active_code != original_code, "replacement voucher has a NEW code")
check(db_one("SELECT pending FROM rewards_recompute WHERE id=1")['pending'] == 0,
      "recompute flag cleared after redeem")

# Reload stability: same persisted code on every GET
codes = set()
for _ in range(2):
    r = c.get('/member/rewards')
    mm = re.search(rb'data-qr="(FS-RED-[A-Z0-9]{8})"', r.data)
    codes.add(mm.group(1).decode())
check(codes == {active_code}, "reloads show the exact persisted code (stable, not regenerated)")

# ============================================================
# 5. GUEST LIFECYCLE: board, pay, leave -> all credited to host
# ============================================================
r = c.post('/member/guest/create', data={'guest_name': 'Vera Visitor'}, follow_redirects=True)
check(b'Guest ID Created' in r.data, "alice creates a guest day-pass (referral +50 pts)")
guest = db_one("SELECT * FROM guest_ids WHERE guest_name='Vera Visitor' ORDER BY id DESC LIMIT 1")
guest_code = guest['guest_code']

logout(c)
c3 = app.test_client()
r = c3.post('/login', data={'guest_code': guest_code}, follow_redirects=True)
check(b'Vera Visitor' in r.data and b'Hosted by' in r.data and b'Alice Johnson' in r.data,
      "guest signs in via day-pass, linked to host Alice")

# Baseline before the guest session (Alice already has her OWN facility row)
alice_fac_acts_before = db_one(
    "SELECT COUNT(*) c FROM activities WHERE member_id=? AND service_name LIKE 'Facility Use%'", (alice_id,))['c']

# Guest checks in and out of a facility
r = c3.post('/guest/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
check(b'Checked in to Club Fitness' in r.data, "guest checks in to facility")
r = c3.post('/guest/scan', data={'facility_code': 'FAC-101'}, follow_redirects=True)
check(b'Checked out of Club Fitness' in r.data, "guest checks out (session completed)")

check(db_one("SELECT COUNT(*) c FROM guest_activities WHERE guest_id=? AND activity_type='facility'", (guest['id'],))['c'] == 1,
      "guest facility session logged on guest ledger")
check(db_one("SELECT COUNT(*) c FROM activities WHERE member_id=? AND service_name LIKE 'Facility Use%'", (alice_id,))['c'] == alice_fac_acts_before,
      "guest session NOT written to host member activity log (count unchanged)")

# Guest pays at the bistro -> host credited
r = c3.post('/guest/spending', data={'service_name': 'Bistro Lunch', 'amount': '25.50'}, follow_redirects=True)
check(b'credited to your host' in r.data, "guest purchase recorded and credited to host")
summary = EngagementEngine.calculate_engagement_score(alice_id)
check(round(summary['guest_spending'], 2) >= 25.50, "host guest_spending reflects $25.50 (%s)" % summary['guest_spending'])

# Guest scans a receipt -> also credited to host
c4 = app.test_client()
login(c4, 'admin', 'admin123')
c4.post('/admin/receipts/issue', data={'service_name': 'Spa Verify', 'amount': '95.00'}, follow_redirects=True)
logout(c4)
spa_code = db_one("SELECT receipt_code FROM receipts WHERE service_name='Spa Verify' ORDER BY id DESC LIMIT 1")['receipt_code']
r = c3.post('/guest/receipts/scan', data={'receipt_code': spa_code}, follow_redirects=True)
check(b'credited to your host member' in r.data, "guest scans receipt -> credited to host")
check(round(EngagementEngine.calculate_engagement_score(alice_id)['guest_spending'], 2) >= 120.50,
      "host guest_spending now >= $120.50 (25.50 + 95.00)")

# Guest logout -> bounced back to login guest tab
r = c3.post('/guest/logout', follow_redirects=True)
check(b'Signed out of your guest day pass' in r.data or b'Sign In' in r.data, "guest logs out cleanly")

# ============================================================
# 6. FEE PAYOFF: fully paid fee can't be over-credited
# ============================================================
conn = get_db()
# Undo the earlier overdraft-drain so Alice has points again for this test.
conn.execute("DELETE FROM point_transactions WHERE member_id=? AND reason='Verify drain'", (alice_id,))
conn.execute("UPDATE members SET yearly_fee=50.0, fee_points_applied=0.0, fee_paid=0 WHERE id=?", (alice_id,))
conn.commit()
conn.close()
r = c.post('/member/marketplace/fee', data={'points': '500'}, follow_redirects=True)
check(b'pts converted to' in r.data, "large fee credit accepted")
fee2 = MarketplaceManager.get_member_fee(alice_id)
check(fee2['remaining'] == 0.0 and fee2['fee_paid'] is True, "fee fully paid and marked paid")
r = c.post('/member/marketplace/fee', data={'points': '10'}, follow_redirects=True)
check(b'already paid' in r.data, "further credit rejected once paid")

# ============================================================
# 7. READ PATHS: CSV exports render (admin-only routes)
# ============================================================
c_admin = app.test_client()
login(c_admin, 'admin', 'admin123')
r = c_admin.get('/admin/reports/export/rewards_csv')
check(r.status_code == 200 and b'Total Points Earned' in r.data, "rewards CSV export renders")
r = c_admin.get('/admin/reports/export/usage_csv')
check(r.status_code == 200 and b'Member Code' in r.data, "usage CSV export renders")

print()
if FAILURES:
    print("%d FAILURE(S):" % len(FAILURES))
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL BEHAVIORAL CHECKS PASSED")
