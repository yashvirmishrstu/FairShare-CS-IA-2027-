import pytest
import os
from database import init_db, get_db
from models import EngagementEngine, RewardSettings, FacilityTracker, GuestManager, CSVReportGenerator, MarketplaceManager

@pytest.fixture(autouse=True)
def setup_test_database(tmp_path, monkeypatch):
    """Set up temporary SQLite database for testing."""
    test_db = os.path.join(tmp_path, "test_fairshare.db")
    monkeypatch.setattr('config.Config.DATABASE', test_db)
    init_db()
    yield test_db

def test_engagement_score_and_discount_calculation():
    conn = get_db()
    cursor = conn.cursor()
    
    # Get test member Alice
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()

    summary = EngagementEngine.calculate_engagement_score(alice_id)
    # Alice has 1 visit (10 pts), $180.50 spending (90.25 pts), 2 referrals (100 pts)
    assert summary['engagement_score'] > 0
    assert summary['visit_count'] >= 1
    assert summary['visit_points'] >= 10.0
    assert summary['spending_points'] >= 90.0
    assert summary['referral_points'] >= 100.0
    # All data sources are present in the breakdown
    assert 'facility_minutes' in summary
    assert 'facility_points' in summary
    assert 'loyalty_months' in summary
    assert 'loyalty_points' in summary
    assert 'tier_multiplier' in summary
    assert summary['tier_multiplier'] == 1.0
    assert summary['base_score'] > 0
    assert summary['engagement_score'] == round(summary['base_score'] * summary['tier_multiplier'], 2)

    discount = EngagementEngine.calculate_discount_band(summary['engagement_score'])
    assert discount in [0.0, 5.0, 10.0, 15.0, 20.0]

def test_facility_checkin_checkout_duration():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    conn.close()

    checkin_id = FacilityTracker.check_in(m_id, "Gym & Fitness")
    assert checkin_id is not None

    duration = FacilityTracker.check_out(checkin_id)
    assert duration >= 1

def test_guest_facility_checkin_checkout_logs_on_guest_ledger():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    host_id = cursor.fetchone()['id']
    conn.close()

    guest_res = GuestManager.create_guest_id(host_id, "Fiona Visitor")
    guest_id = guest_res['id']

    # Guest checks into a facility linked to their host member
    checkin_id = FacilityTracker.guest_check_in(guest_id, host_id, "Swimming Pool & Spa")
    assert checkin_id is not None
    duration = FacilityTracker.check_out(checkin_id)
    assert duration >= 1

    # Guest session lands on the guest ledger, NOT the host member's activity log
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM guest_activities WHERE guest_id = ? AND activity_type = 'facility'", (guest_id,))
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM activities WHERE member_id = ? AND service_name LIKE 'Facility Use%'", (host_id,))
    assert cursor.fetchone()[0] == 0
    conn.close()

def test_guest_creation_and_spending():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    host_id = cursor.fetchone()['id']
    conn.close()

    guest_res = GuestManager.create_guest_id(host_id, "David Miller")
    assert guest_res['guest_code'].startswith("GST-")

    success = GuestManager.record_guest_spending(guest_res['guest_code'], "Tennis Shop", 150.00)
    assert success is True

    # Verify that guest spending is reflected in host member engagement calculation
    summary = EngagementEngine.calculate_engagement_score(host_id)
    assert summary['guest_spending'] >= 150.00

def test_facility_usage_minutes_add_points():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    conn.close()

    # Baseline facility points (seed data has no completed check-ins)
    baseline = EngagementEngine.calculate_engagement_score(m_id)

    # Complete a facility session
    checkin_id = FacilityTracker.check_in(m_id, "Gym & Fitness")
    FacilityTracker.check_out(checkin_id)

    summary = EngagementEngine.calculate_engagement_score(m_id)
    assert summary['facility_minutes'] > baseline['facility_minutes']
    assert summary['facility_points'] >= baseline['facility_points']
    assert summary['engagement_score'] > baseline['engagement_score']

def test_loyalty_months_award_points():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    # Backdate the join date to 6 months ago to simulate a loyal member
    from datetime import datetime, timedelta
    old_join = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    cursor.execute("UPDATE members SET join_date = ? WHERE id = ?", (old_join, m_id))
    conn.commit()
    conn.close()

    summary = EngagementEngine.calculate_engagement_score(m_id)
    assert summary['loyalty_months'] >= 5
    assert summary['loyalty_points'] >= summary['loyalty_months'] * 5.0

def test_membership_tier_multiplier_boosts_score():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    cursor.execute("UPDATE members SET membership_type = 'Premium' WHERE id = ?", (m_id,))
    conn.commit()
    conn.close()

    summary = EngagementEngine.calculate_engagement_score(m_id)
    settings = RewardSettings.get_settings()
    assert summary['membership_type'] == 'Premium'
    assert summary['tier_multiplier'] == settings['premium_multiplier']
    assert summary['engagement_score'] == round(summary['base_score'] * summary['tier_multiplier'], 2)
    assert summary['engagement_score'] >= summary['base_score']

def test_tier_normalization_and_multiplier_lookup():
    """Every tier spelling resolves to the canonical tier and its multiplier,
    and unknown tiers fall back to the base Member multiplier (1.0)."""
    settings = RewardSettings.get_settings()

    # normalize_tier: canonical spellings, mixed case, whitespace, aliases
    assert EngagementEngine.normalize_tier('Member') == 'Member'
    assert EngagementEngine.normalize_tier('Premium') == 'Premium'
    assert EngagementEngine.normalize_tier('VIP') == 'VIP'
    assert EngagementEngine.normalize_tier('premium') == 'Premium'
    assert EngagementEngine.normalize_tier('vip') == 'VIP'
    assert EngagementEngine.normalize_tier('  Premium  ') == 'Premium'
    assert EngagementEngine.normalize_tier('') == 'Member'
    assert EngagementEngine.normalize_tier(None) == 'Member'
    assert EngagementEngine.normalize_tier('Gold') == 'Member'  # unknown -> Member

    # tier_multiplier: uses the live settings values for paid tiers
    assert EngagementEngine.tier_multiplier('Member', settings) == 1.0
    assert EngagementEngine.tier_multiplier('Premium', settings) == settings['premium_multiplier']
    assert EngagementEngine.tier_multiplier('VIP', settings) == settings['vip_multiplier']
    assert EngagementEngine.tier_multiplier('premium', settings) == settings['premium_multiplier']
    assert EngagementEngine.tier_multiplier('vip ', settings) == settings['vip_multiplier']
    assert EngagementEngine.tier_multiplier('Platinum', settings) == 1.0

def test_membership_type_persists_and_multiplier_applies():
    """Changing membership_type to VIP applies the VIP multiplier from settings."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    cursor.execute("UPDATE members SET membership_type = 'VIP' WHERE id = ?", (m_id,))
    conn.commit()
    conn.close()

    settings = RewardSettings.get_settings()
    summary = EngagementEngine.calculate_engagement_score(m_id)
    assert summary['membership_type'] == 'VIP'
    assert summary['tier_multiplier'] == settings['vip_multiplier']
    assert summary['engagement_score'] == round(summary['base_score'] * settings['vip_multiplier'], 2)

def test_settings_update():
    RewardSettings.update_settings(15.0, 1.0, 60.0, 0.5, 8.0, 15000.00, 1.2, 1.5)
    settings = RewardSettings.get_settings()
    assert settings['visit_weight'] == 15.0
    assert settings['spending_weight'] == 1.0
    assert settings['referral_weight'] == 60.0
    assert settings['facility_weight'] == 0.5
    assert settings['loyalty_weight'] == 8.0
    assert settings['premium_multiplier'] == 1.2
    assert settings['vip_multiplier'] == 1.5
    assert settings['profit_sharing_pool'] == 15000.00


def test_batch_scores_match_single_member_lookup():
    """The batch pass must produce the same summary for every member as the
    per-member lookup — the grouped queries must not change the math."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members")
    member_ids = [r['id'] for r in cursor.fetchall()]
    conn.close()

    batch = EngagementEngine.calculate_all_scores()
    assert len(batch) == len(member_ids)

    for m_id in member_ids:
        assert m_id in batch, f"member {m_id} missing from batch pass"
        single = EngagementEngine.calculate_engagement_score(m_id)
        for key in ('visit_count', 'total_spending', 'guest_referrals',
                    'facility_minutes', 'loyalty_months', 'base_score',
                    'tier_multiplier', 'engagement_score'):
            assert batch[m_id][key] == single[key], \
                f"batch/single mismatch on {key} for member {m_id}"


def test_recalculate_all_upserts_rewards_and_preserves_codes():
    """A scoring write marks the cache dirty (trigger); recalculate_all() then
    creates one active reward row per member and updates (never duplicates)
    them on subsequent changes, keeping redemption codes stable."""
    # No reward rows exist yet
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT id FROM members")
    member_ids = [r['id'] for r in cursor.fetchall()]
    conn.close()

    # A scoring write fires the dirty trigger; the recompute materializes rows
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) "
                   "VALUES (?, 'purchase', 'Initial Purchase', 10.0)", (member_ids[0],))
    conn.commit()
    conn.close()

    rewards_map = EngagementEngine.recalculate_all()
    assert set(rewards_map.keys()) == set(member_ids)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT member_id, redemption_code FROM rewards WHERE status='active'")
    first = {r['member_id']: r['redemption_code'] for r in cursor.fetchall()}
    conn.close()
    assert len(first) == len(member_ids)  # exactly one active row per member

    # Data changes (add an activity) then recompute — rows update, codes persist
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) VALUES (?, 'purchase', 'New Purchase', 50.0)", (member_ids[0],))
    conn.commit()
    conn.close()
    EngagementEngine.recalculate_all()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT member_id, redemption_code, engagement_score FROM rewards WHERE status='active'")
    second = {r['member_id']: (r['redemption_code'], r['engagement_score']) for r in cursor.fetchall()}
    conn.close()

    assert len(second) == len(member_ids)  # no duplicate rows after recompute
    for m_id in member_ids:
        assert second[m_id][0] == first[m_id]  # redemption code survived
    # The member whose spending grew now has a higher stored score
    assert second[member_ids[0]][1] > rewards_map[member_ids[0]]['engagement_score']


def test_marketplace_coupons_seeded_and_active():
    """The demo coupon catalog is seeded with active, affordably-priced
    coupons spanning the marketplace categories."""
    coupons = MarketplaceManager.get_active_coupons()
    assert len(coupons) >= 4
    assert all(c['active'] == 1 for c in coupons)
    assert all(c['cost_points'] > 0 for c in coupons)
    categories = {c['category'] for c in coupons}
    assert 'Facility' in categories


def test_claim_coupon_deducts_points_and_issues_code():
    """Claiming a coupon deducts points, records a ledger entry, and issues
    a unique CPN- code linked to the member."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()

    EngagementEngine.recalculate_all()
    before = EngagementEngine.view_member_rewards(alice_id)
    coupon = MarketplaceManager.get_active_coupons()[0]

    result = MarketplaceManager.claim_coupon(alice_id, coupon['id'])
    assert result['ok'] is True
    assert result['coupon_code'].startswith('CPN-')

    after = EngagementEngine.view_member_rewards(alice_id)
    assert after['points_balance'] == round(before['points_balance'] - coupon['cost_points'], 2)
    assert after['points_spent'] == round(before['points_spent'] + coupon['cost_points'], 2)

    claimed = MarketplaceManager.get_member_coupons(alice_id)
    assert len(claimed) == 1
    assert claimed[0]['coupon_code'] == result['coupon_code']
    assert claimed[0]['name'] == coupon['name']

    ledger = MarketplaceManager.get_point_transactions(alice_id)
    assert ledger and ledger[0]['points_delta'] == -coupon['cost_points']


def test_claim_coupon_rejects_insufficient_balance():
    """A member without enough spendable points cannot claim an expensive
    coupon, and no ledger entry is written."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()

    EngagementEngine.recalculate_all()
    # Spend every point Alice has on a coupon first
    coupons = MarketplaceManager.get_active_coupons()
    cheapest = min(coupons, key=lambda c: c['cost_points'])
    # Drain the balance by claiming the cheapest coupon repeatedly via direct ledger writes
    balance = EngagementEngine.view_member_rewards(alice_id)['points_balance']
    cursor = get_db()
    cur = cursor.cursor()
    cur.execute("INSERT INTO point_transactions (member_id, points_delta, reason) VALUES (?, ?, ?)",
                (alice_id, -balance, 'Test drain'))
    cursor.commit()
    cursor.close()

    result = MarketplaceManager.claim_coupon(alice_id, cheapest['id'])
    assert result['ok'] is False
    assert 'Insufficient points' in result['message']
    assert len(MarketplaceManager.get_member_coupons(alice_id)) == 0


def test_apply_points_to_fee_credits_dollars():
    """Points convert to dollars at the configured rate and reduce the
    remaining yearly fee; over-crediting clamps to the exact fee balance."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    conn.close()

    EngagementEngine.recalculate_all()
    settings = RewardSettings.get_settings()
    rate = settings['points_value_dollars']
    fee_before = MarketplaceManager.get_member_fee(alice_id)

    result = MarketplaceManager.apply_points_to_fee(alice_id, 100)
    assert result['ok'] is True
    assert result['credited'] == round(100 * rate, 2)
    assert result['remaining'] == round(fee_before['remaining'] - 100 * rate, 2)

    fee_after = MarketplaceManager.get_member_fee(alice_id)
    assert fee_after['fee_points_applied'] == round(fee_before['fee_points_applied'] + 100 * rate, 2)
    assert fee_after['remaining'] == result['remaining']

    # Balance shrinks by the points spent
    rewards = EngagementEngine.view_member_rewards(alice_id)
    assert rewards['points_spent'] == 100.0


def test_apply_points_to_fee_pays_off_and_marks_paid():
    """Crediting enough points to cover the whole fee marks it paid and
    rejects further applications."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    # Set a small yearly fee so Alice's points can fully cover it
    cursor.execute("UPDATE members SET yearly_fee = 50.0 WHERE id = ?", (alice_id,))
    conn.commit()
    conn.close()

    EngagementEngine.recalculate_all()
    fee = MarketplaceManager.get_member_fee(alice_id)
    rate = fee['points_value_dollars']
    needed_points = int(fee['remaining'] / rate) + 1  # slightly over

    result = MarketplaceManager.apply_points_to_fee(alice_id, needed_points)
    assert result['ok'] is True
    assert result['remaining'] == 0.0

    fee_after = MarketplaceManager.get_member_fee(alice_id)
    assert fee_after['fee_paid'] is True
    assert fee_after['remaining'] == 0.0

    # Further credit rejected once paid
    blocked = MarketplaceManager.apply_points_to_fee(alice_id, 10)
    assert blocked['ok'] is False
    assert 'already paid' in blocked['message']


def test_apply_points_to_fee_clamps_over_credit_to_fee_need():
    """Crediting MORE points than the remaining fee needs must consume only
    what the fee requires — a round-number request can never burn surplus
    points against a small fee, and the request is accepted as long as the
    fee's real need is affordable."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    # A small fee so Alice's balance dwarfs the real need but not her raw
    # round-number request.
    cursor.execute("UPDATE members SET yearly_fee = 50.0 WHERE id = ?", (alice_id,))
    conn.commit()
    conn.close()

    EngagementEngine.recalculate_all()
    rate = RewardSettings.get_settings()['points_value_dollars']
    fee_need_dollars = 50.0
    needed_points = round(fee_need_dollars / rate, 2)

    balance = EngagementEngine.view_member_rewards(alice_id)['points_balance']
    # Alice must be able to afford the fee's real need but her raw request
    # (500) exceeds her balance — the clamp must make it succeed.
    assert balance >= needed_points, "seed balance should cover the fee need"

    result = MarketplaceManager.apply_points_to_fee(alice_id, 500)
    assert result['ok'] is True, result['message']
    assert result['credited'] == round(fee_need_dollars, 2)
    assert result['remaining'] == 0.0

    # Exactly the needed points were consumed — not the full 500 request.
    fee = MarketplaceManager.get_member_fee(alice_id)
    assert fee['fee_paid'] is True
    assert fee['fee_points_applied'] == round(fee_need_dollars, 2)

    ledger = MarketplaceManager.get_point_transactions(alice_id)
    fee_debits = [t for t in ledger if t['reason'] == 'Yearly membership fee credit']
    assert len(fee_debits) == 1
    assert fee_debits[0]['points_delta'] == -needed_points

    # Once paid, further credits are rejected.
    blocked = MarketplaceManager.apply_points_to_fee(alice_id, 10)
    assert blocked['ok'] is False
    assert 'already paid' in blocked['message']


def test_points_balance_equals_earned_minus_spent():
    """points_balance is exactly lifetime earned minus everything spent in
    the ledger, and never dips below zero."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Bob Smith'")
    bob_id = cursor.fetchone()['id']
    conn.close()

    EngagementEngine.recalculate_all()
    rewards = EngagementEngine.view_member_rewards(bob_id)
    assert rewards['points_balance'] == round(rewards['engagement_score'] - rewards['points_spent'], 2)
    assert rewards['points_balance'] >= 0

    # After a coupon claim the identity still holds
    coupons = MarketplaceManager.get_active_coupons()
    affordable = [c for c in coupons if c['cost_points'] <= rewards['points_balance']]
    if affordable:
        MarketplaceManager.claim_coupon(bob_id, affordable[0]['id'])
        rewards2 = EngagementEngine.view_member_rewards(bob_id)
        assert rewards2['points_balance'] == round(rewards2['engagement_score'] - rewards2['points_spent'], 2)


def test_rewards_view_and_csv_export_are_read_only_when_clean():
    """When the rewards cache is clean (no scoring write since the last
    recompute), view_all_rewards() and the financial CSV export never write to
    the database — a fresh DB starts clean, so these are pure reads."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    assert cursor.fetchone()['pending'] == 0  # fresh DB starts clean
    cursor.execute("SELECT COUNT(*) FROM rewards")
    assert cursor.fetchone()[0] == 0
    conn.close()

    # Clean cache: both read paths must not create reward rows
    view = EngagementEngine.view_all_rewards()
    assert len(view) > 0  # summaries computed on the fly for seeded members

    csv_data = CSVReportGenerator.export_financial_reward_summaries()
    assert 'Total Points Earned' in csv_data
    assert 'Member Code' in csv_data

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards")
    assert cursor.fetchone()[0] == 0, "clean-cache views must not insert reward rows"
    conn.close()


def test_scoring_write_marks_dirty_and_recompute_clears():
    """A scoring-relevant write fires a SQLite trigger that sets the recompute
    flag; recalculate_all() materializes rows and clears it."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) "
                   "VALUES (?, 'purchase', 'Dirty Me', 5.0)", (m_id,))
    conn.commit()
    cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    assert cursor.fetchone()['pending'] == 1, "trigger must mark the cache dirty"
    conn.close()

    EngagementEngine.recalculate_all()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    assert cursor.fetchone()['pending'] == 0
    cursor.execute("SELECT COUNT(*) FROM rewards WHERE status='active'")
    assert cursor.fetchone()[0] > 0
    conn.close()


def test_view_lazily_materializes_once_when_dirty():
    """The first rewards view after a scoring write materializes rows and
    clears the flag; a second view writes nothing (pure read)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members LIMIT 1")
    m_id = cursor.fetchone()['id']
    cursor.execute("INSERT INTO activities (member_id, activity_type, service_name, transaction_value) "
                   "VALUES (?, 'purchase', 'Lazy', 5.0)", (m_id,))
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM rewards")
    assert cursor.fetchone()[0] == 0
    conn.close()

    view = EngagementEngine.view_all_rewards()
    assert m_id in view

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards WHERE status='active'")
    n1 = cursor.fetchone()[0]
    cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    assert cursor.fetchone()['pending'] == 0
    conn.close()
    assert n1 > 0

    EngagementEngine.view_all_rewards()  # flag clean now — no writes
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards WHERE status='active'")
    assert cursor.fetchone()[0] == n1
    conn.close()


def test_recalculate_all_force_writes_even_when_clean():
    """force=True materializes reward rows even when the cache is clean."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT pending FROM rewards_recompute WHERE id = 1")
    assert cursor.fetchone()['pending'] == 0
    cursor.execute("SELECT COUNT(*) FROM rewards")
    assert cursor.fetchone()[0] == 0
    conn.close()

    EngagementEngine.recalculate_all(force=True)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM rewards WHERE status='active'")
    assert cursor.fetchone()[0] > 0
    conn.close()


def _alice_id():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    member_id = cursor.fetchone()['id']
    conn.close()
    return member_id


def test_claim_coupon_rejects_unknown_coupon_id():
    """Claiming a coupon id that does not exist is rejected with no writes:
    no coupon row and no point ledger entry."""
    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    result = MarketplaceManager.claim_coupon(alice_id, 999999)
    assert result['ok'] is False
    assert 'no longer available' in result['message']
    assert len(MarketplaceManager.get_member_coupons(alice_id)) == 0
    assert MarketplaceManager.get_point_transactions(alice_id) == []


def test_claim_coupon_rejects_deactivated_coupon():
    """A coupon the admin has deactivated (expired) cannot be claimed and
    writes nothing, even though the member has plenty of points."""
    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    coupon = MarketplaceManager.get_active_coupons()[0]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE coupons SET active = 0 WHERE id = ?", (coupon['id'],))
    conn.commit()
    conn.close()

    result = MarketplaceManager.claim_coupon(alice_id, coupon['id'])
    assert result['ok'] is False
    assert 'no longer available' in result['message']
    assert len(MarketplaceManager.get_member_coupons(alice_id)) == 0
    assert MarketplaceManager.get_point_transactions(alice_id) == []


def test_claim_coupon_rejects_double_redemption_when_balance_short():
    """Double redemption guard: claiming the same coupon a second time must be
    rejected when the remaining balance cannot cover it, and the failed claim
    leaves no extra coupon row or ledger entry."""
    alice_id = _alice_id()
    EngagementEngine.recalculate_all()
    balance = EngagementEngine.view_member_rewards(alice_id)['points_balance']

    # Create a coupon that costs just over half the balance, so one claim
    # succeeds but a second one cannot be afforded.
    cost = round(balance / 2, 2) + 1.0
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO coupons (name, description, category, cost_points, value_amount, facility_name, active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    ''', ('Half-Balance Pass', 'Costs just over half of Alice balance.', 'Facility', cost, 0.0, None))
    coupon_id = cursor.lastrowid
    conn.commit()
    conn.close()

    first = MarketplaceManager.claim_coupon(alice_id, coupon_id)
    assert first['ok'] is True

    second = MarketplaceManager.claim_coupon(alice_id, coupon_id)
    assert second['ok'] is False
    assert 'Insufficient points' in second['message']

    # Only ONE coupon row exists, and the ledger holds exactly one debit
    # for this coupon — the rejected claim wrote nothing.
    claimed = MarketplaceManager.get_member_coupons(alice_id)
    assert len(claimed) == 1
    assert claimed[0]['coupon_id'] == coupon_id
    ledger = MarketplaceManager.get_point_transactions(alice_id)
    coupon_debits = [t for t in ledger if 'Claimed coupon' in t['reason']]
    assert len(coupon_debits) == 1
    assert coupon_debits[0]['points_delta'] == -cost


def test_claim_coupon_insufficient_balance_writes_nothing():
    """An insufficient-balance claim is fully atomic: no member_coupon row
    and no point_transactions row are created."""
    alice_id = _alice_id()
    EngagementEngine.recalculate_all()
    balance = EngagementEngine.view_member_rewards(alice_id)['points_balance']

    expensive = round(balance * 10, 2)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO coupons (name, description, category, cost_points, value_amount, facility_name, active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    ''', ('Impossible Pass', 'Costs 10x the available balance.', 'Events', expensive, 0.0, None))
    coupon_id = cursor.lastrowid
    conn.commit()
    conn.close()

    result = MarketplaceManager.claim_coupon(alice_id, coupon_id)
    assert result['ok'] is False
    assert 'Insufficient points' in result['message']
    assert len(MarketplaceManager.get_member_coupons(alice_id)) == 0
    assert MarketplaceManager.get_point_transactions(alice_id) == []


def test_concurrent_claims_never_double_spend():
    """Concurrent claims for the same coupon must not both pass the balance
    check: the BEGIN IMMEDIATE write lock serializes them, so the points
    balance is never double-spent. Exactly one claim succeeds."""
    import threading

    alice_id = _alice_id()
    EngagementEngine.recalculate_all()
    balance = EngagementEngine.view_member_rewards(alice_id)['points_balance']

    # Cost just over half the balance: only ONE of two concurrent claims can
    # afford it.
    cost = round(balance / 2, 2) + 1.0
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO coupons (name, description, category, cost_points, value_amount, facility_name, active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    ''', ('Race Pass', 'Two threads race to claim it.', 'Events', cost, 0.0, None))
    coupon_id = cursor.lastrowid
    conn.commit()
    conn.close()

    results = []
    barrier = threading.Barrier(2)

    def claim():
        barrier.wait()  # maximize overlap so both hit the balance check together
        results.append(MarketplaceManager.claim_coupon(alice_id, coupon_id))

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_count = sum(1 for r in results if r['ok'])
    assert ok_count == 1, f'exactly one claim should succeed, got {results}'

    claimed = MarketplaceManager.get_member_coupons(alice_id)
    assert len(claimed) == 1
    assert claimed[0]['coupon_id'] == coupon_id

    # Total points spent never exceeds what was available.
    ledger = MarketplaceManager.get_point_transactions(alice_id)
    total_spent = sum(-t['points_delta'] for t in ledger if t['points_delta'] < 0)
    assert total_spent <= balance


def test_concurrent_fee_credits_never_over_credit():
    """Concurrent yearly-fee credits cannot both consume the same points:
    the write lock serializes them and total credits never exceed the
    available balance."""
    import threading

    alice_id = _alice_id()
    EngagementEngine.recalculate_all()
    balance = EngagementEngine.view_member_rewards(alice_id)['points_balance']
    half = round(balance / 2, 2) + 1.0

    results = []
    barrier = threading.Barrier(2)

    def credit():
        barrier.wait()
        results.append(MarketplaceManager.apply_points_to_fee(alice_id, half))

    threads = [threading.Thread(target=credit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_count = sum(1 for r in results if r['ok'])
    assert ok_count == 1, f'exactly one fee credit should succeed, got {results}'

    ledger = MarketplaceManager.get_point_transactions(alice_id)
    total_spent = sum(-t['points_delta'] for t in ledger if t['points_delta'] < 0)
    assert total_spent <= balance


def _claim_for(member_id):
    """Claim the cheapest active coupon and return the issued coupon code."""
    coupons = MarketplaceManager.get_active_coupons()
    assert coupons, 'expected seeded coupons'
    cheapest = min(coupons, key=lambda c: c['cost_points'])
    result = MarketplaceManager.claim_coupon(member_id, cheapest['id'])
    assert result['ok'] is True, result['message']
    return result['coupon_code'], cheapest['id']


def test_use_coupon_redeems_active_coupon_once():
    """Redeeming an active coupon flips it to 'used', stamps used_at, and
    refuses any second redemption of the same code."""
    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    code, _coupon_id = _claim_for(alice_id)

    result = MarketplaceManager.use_coupon(code, alice_id)
    assert result['ok'] is True
    assert 'redeemed' in result['message'].lower()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status, used_at FROM member_coupons WHERE coupon_code = ?", (code,))
    row = cursor.fetchone()
    conn.close()
    assert row['status'] == 'used'
    assert row['used_at'] is not None

    # Second redemption of the same code is rejected and changes nothing.
    again = MarketplaceManager.use_coupon(code, alice_id)
    assert again['ok'] is False
    assert 'already been used' in again['message']

    # The member's coupon list still shows the row (now annotated as used).
    claimed = MarketplaceManager.get_member_coupons(alice_id)
    assert any(c['coupon_code'] == code and c['status'] == 'used' for c in claimed)


def test_use_coupon_rejects_unknown_code():
    """A code that was never issued is rejected with a clear message."""
    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    result = MarketplaceManager.use_coupon('CPN-DEADBEEF', alice_id)
    assert result['ok'] is False
    assert 'not found' in result['message']


def test_use_coupon_rejects_foreign_member_code():
    """Alice cannot redeem a coupon code that belongs to Bob."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE full_name = 'Alice Johnson'")
    alice_id = cursor.fetchone()['id']
    cursor.execute("SELECT id FROM members WHERE full_name = 'Bob Smith'")
    bob_id = cursor.fetchone()['id']
    coupon_id = MarketplaceManager.get_active_coupons()[0]['id']
    # Insert Bob's coupon row directly (Bob's balance is below the cheapest
    # catalog price, but the ownership guard must not depend on that).
    cursor.execute('''
        INSERT INTO member_coupons (member_id, coupon_id, coupon_code, points_spent, status)
        VALUES (?, ?, ?, 40.0, 'active')
    ''', (bob_id, coupon_id, 'CPN-FOREIGN1'))
    conn.commit()
    conn.close()

    code = 'CPN-FOREIGN1'

    result = MarketplaceManager.use_coupon(code, alice_id)
    assert result['ok'] is False
    assert 'different member' in result['message']

    # Bob can still redeem his own coupon afterwards (untouched by the attempt).
    result = MarketplaceManager.use_coupon(code, bob_id)
    assert result['ok'] is True


def test_use_coupon_rejects_expired_coupon():
    """A claimed coupon past its validity window cannot be redeemed — the
    row stays 'active' but is refused by the expiry check."""
    from datetime import datetime, timedelta

    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    code, _ = _claim_for(alice_id)

    # Backdate the claim beyond the validity window.
    old = (datetime.now() - timedelta(days=MarketplaceManager.coupon_valid_days() + 1)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE member_coupons SET claimed_at = ? WHERE coupon_code = ?", (old, code))
    conn.commit()
    conn.close()

    assert MarketplaceManager.is_coupon_expired(old) is True

    result = MarketplaceManager.use_coupon(code, alice_id)
    assert result['ok'] is False
    assert 'expired' in result['message']

    # The row was NOT flipped to used — it simply cannot be redeemed.
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM member_coupons WHERE coupon_code = ?", (code,))
    assert cursor.fetchone()['status'] == 'active'
    conn.close()


def test_use_coupon_expired_message_reports_expiry_date():
    """The expired-coupon refusal names the EXPIRY date (claim date + the
    validity window), not the claim date — a regression test for the fix
    that previously printed claimed_at[:10] (the day it was claimed)."""
    from datetime import datetime, timedelta

    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    code, _ = _claim_for(alice_id)

    # Backdate the claim beyond the validity window and record BOTH dates.
    claim_dt = datetime.now() - timedelta(days=MarketplaceManager.coupon_valid_days() + 1)
    claim_str = claim_dt.strftime("%Y-%m-%d %H:%M:%S")
    expiry_str = (claim_dt + timedelta(days=MarketplaceManager.coupon_valid_days())).strftime("%Y-%m-%d")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE member_coupons SET claimed_at = ? WHERE coupon_code = ?", (claim_str, code))
    conn.commit()
    conn.close()

    result = MarketplaceManager.use_coupon(code, alice_id)
    assert result['ok'] is False
    # The message names the expiry date, not the claim date.
    assert expiry_str in result['message'], result['message']
    assert claim_str[:10] not in result['message'], result['message']


def test_use_coupon_unparseable_claimed_at_degrades_gracefully():
    """A coupon whose claimed_at cannot be parsed is treated as NOT expired
    (documented fail-open default) and remains redeemable — it must neither
    crash the redemption desk nor be silently voided by the expiry check."""
    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    code, _ = _claim_for(alice_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE member_coupons SET claimed_at = 'not-a-date' WHERE coupon_code = ?", (code,))
    conn.commit()
    conn.close()

    # The expiry helpers degrade gracefully...
    assert MarketplaceManager.coupon_expires_at('not-a-date') is None
    assert MarketplaceManager.is_coupon_expired('not-a-date') is False
    # ...so the coupon is still redeemable (no crash, no false refusal).
    result = MarketplaceManager.use_coupon(code, alice_id)
    assert result['ok'] is True, result['message']


def test_coupon_expiry_helpers():
    """coupon_expires_at / is_coupon_expired compute the validity window,
    and unparseable timestamps degrade to a safe (not-expired) default."""
    from datetime import datetime, timedelta

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expires = MarketplaceManager.coupon_expires_at(now_str)
    assert expires is not None
    # coupon_expires_at truncates to whole seconds, so the remaining window is
    # 30 days minus the microseconds fraction of `now` — assert a tolerance.
    elapsed = expires - now
    assert timedelta(days=MarketplaceManager.coupon_valid_days() - 1) < elapsed <= timedelta(days=MarketplaceManager.coupon_valid_days())
    assert MarketplaceManager.is_coupon_expired(now_str) is False

    # Clear-cut boundaries: one day inside the window is still valid, one
    # day past it is expired. (The exact 30-day edge is sub-second racy —
    # claimed_at truncates to seconds while datetime.now() keeps microseconds
    # — so the test deliberately stays a full day away from it.)
    just_before = (now - timedelta(days=MarketplaceManager.coupon_valid_days() - 1)).strftime("%Y-%m-%d %H:%M:%S")
    assert MarketplaceManager.is_coupon_expired(just_before) is False

    just_after = (now - timedelta(days=MarketplaceManager.coupon_valid_days() + 1)).strftime("%Y-%m-%d %H:%M:%S")
    assert MarketplaceManager.is_coupon_expired(just_after) is True

    # Defensive default: garbage timestamps never void a coupon.
    assert MarketplaceManager.coupon_expires_at(None) is None
    assert MarketplaceManager.is_coupon_expired(None) is False
    assert MarketplaceManager.is_coupon_expired('not-a-date') is False


def test_member_coupons_annotated_with_expiry():
    """get_member_coupons enriches each row with expires_at_date / expired so
    the UI can show remaining validity."""
    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    code, _ = _claim_for(alice_id)
    claimed = MarketplaceManager.get_member_coupons(alice_id)
    row = next(c for c in claimed if c['coupon_code'] == code)
    assert row['expired'] is False
    assert row['expires_at_date'] is not None
    assert row['expires_at'] is not None


def test_concurrent_coupon_redeems_never_double_use():
    """Two simultaneous redemptions of the same coupon code: exactly one
    succeeds because the active->used flip is atomic. The coupon can never
    be redeemed twice, even under a race."""
    import threading

    alice_id = _alice_id()
    EngagementEngine.recalculate_all()

    code, _ = _claim_for(alice_id)

    results = []
    barrier = threading.Barrier(2)

    def redeem():
        barrier.wait()  # maximize overlap so both hit the UPDATE together
        results.append(MarketplaceManager.use_coupon(code, alice_id))

    threads = [threading.Thread(target=redeem) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_count = sum(1 for r in results if r['ok'])
    assert ok_count == 1, f'exactly one redemption should succeed, got {results}'

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM member_coupons WHERE coupon_code = ?", (code,))
    assert cursor.fetchone()['status'] == 'used'
    conn.close()

    # And it stays used — a third attempt is also refused.
    final = MarketplaceManager.use_coupon(code, alice_id)
    assert final['ok'] is False
