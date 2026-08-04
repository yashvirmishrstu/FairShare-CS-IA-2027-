# FairShare

A web application for recreational organisations that rewards members based on their engagement and value generated for the organisation.

## Project Overview

FairShare is designed for country clubs and similar recreational organisations to move away from flat subscription models toward a value-based reward system. The system tracks member visits, guest referrals, facility usage, restaurant spending, and shop purchases to calculate an engagement score that is automatically converted into personalised rewards such as discounts, cashback, or redemption codes.

### Core Problem

Traditional clubs charge members a flat fee regardless of their contribution level. Highly active members who visit often, invite guests, and spend money at internal facilities receive no additional recognition, which can reduce loyalty. FairShare solves this by creating a transparent reward cycle that recognises and rewards high-value members.

### The Reward Cycle

1. The member uses club services (visits, purchases, referrals, facility sessions).
2. The system records the activity in a relational database.
3. A batch engagement engine computes each member's engagement score.
4. The score is converted into a personalised discount band and points balance.
5. The member spends points on coupons in the marketplace or credits their yearly fee.
6. Administrators monitor engagement, adjust algorithm settings, and manage the coupon catalog.

## Technology Stack

- **Backend**: Python with Flask
- **Frontend**: HTML, CSS, JavaScript
- **Database**: SQLite (single-file, self-seeding on first launch)
- **Templates**: Jinja HTML templates
- **Authentication**: Flask sessions with hashed passwords (Werkzeug)
- **Barcodes / QR codes**: JsBarcode and QRCode.js (CDN)
- **Charts**: Chart.js
- **Export**: Python CSV module

## Features

### Member Features

- Secure login with hashed (encrypted) passwords
- Personal ID card with a unique scannable barcode (`member_code`) and a print option
- Dashboard showing engagement score, personalised discount, and points balance
- Facility barcode scanning — scan to check in, scan again to check out; session duration is tracked automatically
- Activity and facility-session history
- QR receipt scanning to auto-log expenses from admin-issued receipts
- Guest day-pass creation — every guest activity is credited to the hosting member
- Points marketplace — browse and claim coupons with points, view claimed coupons as QR codes
- Coupon redemption desk — scan a claimed coupon's QR to redeem it for a single use (coupons expire after 30 days)
- Credit points toward the yearly membership fee ($0.50 per point)
- Redemption QR code (e.g. `FS-RED-XXXXXXXX`) for earned vouchers

### Guest Features (Day-Pass)

- Sign in via a guest pass code or QR
- Facility barcode check-in/check-out with duration tracking
- Record purchases — automatically credited to the host member's rewards
- Scan receipts — also credited to the host member

### Administrator Features

- Secure admin login with role-based access control (RBAC)
- Dashboard with club totals and Chart.js analytics (facility usage trends, peak activity hours, reward-band distribution)
- Member management — add/edit members, membership tiers, and yearly fees
- Activity logging, manual check-in/check-out, and receipt issuance
- Reward algorithm settings — weights, tier multipliers, profit pool, and points value
- Coupon marketplace management — add or toggle coupons
- Reports — usage logs and financial reward summaries, exportable as CSV

## Demo Accounts

The database seeds itself on first launch (`data/fairshare.db` is created automatically). No manual setup is required.

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `admin123` |
| Member | `alice` | `password123` |
| Member | `bob` | `password123` |
| Member | `charlie` | `password123` |

Guests do not have standing accounts — a member creates a guest day-pass from the member dashboard, which generates a unique pass code.

> Note: public self-registration is intentionally disabled. Member accounts must be created by an administrator (security decision — least privilege).

## Success Criteria

1. Secure login for members and administrators with encrypted passwords
2. Relational database storage without data duplication
3. Recording of member visits, facility usage, and purchases with timestamps
4. Automatic engagement score calculation based on configurable factors
5. Automatic personalised discount generation based on engagement score
6. Member dashboard displaying reward status, engagement score, and discounts
7. Scanning a unique user ID barcode for facility check-in/check-out
8. Facility usage tracking with duration calculation
9. Guest ID creation for tracking guest visits and spending
10. Admin control panel for algorithm settings and member management
11. Redemption QR code/coupon code generation for discounts
12. Responsive UI for mobile, tablet, and desktop
13. Fast page loading (under 2–3 seconds) with asset caching
14. Admin charts showing usage trends, peak hours, and reward distribution
15. CSV export for member usage logs and financial summaries
16. Client- and server-side validation for data integrity and security

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yashvirmishrstu/FairShare-CS-IA-2027-.git
```

2. Navigate to the Code directory:
```bash
cd Code
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
python main.py
```

5. Open your browser and navigate to `http://127.0.0.1:5000`

The database is created and seeded automatically when the app starts — no `init_db` step or migration command is needed.

## Facility Barcode Registry

Facilities are identified by unique barcode codes; scanning one checks the member (or guest) in, and scanning it again checks them out:

| Barcode | Facility |
|---------|----------|
| `FAC-101` | Club Fitness & Gym |
| `FAC-102` | Tennis & Squash Courts |
| `FAC-103` | Swimming Pool & Spa |
| `FAC-104` | Bistro & Lounge |
| `FAC-105` | Pro Golf Course |

## Project Structure

```
Code/
├── main.py              # Flask controller: routes, auth, validation
├── models.py            # Business logic: engagement engine, rewards, marketplace
├── database.py          # Schema, migrations, seeding, dirty-flag triggers
├── config.py            # Central configuration & algorithm defaults
├── requirements.txt     # Python dependencies
├── verify_behavior.py   # Headless end-to-end lifecycle checks
├── check_endpoints.py   # Endpoint health check (static + live stale-server probe)
├── benchmarks/
│   ├── bench_batch.py        # A/B benchmark: legacy vs batch engagement engine
│   └── _legacy_engine_ref.py # Frozen legacy engine (baseline for comparison)
├── data/
│   └── fairshare.db     # SQLite database (self-seeding)
├── static/
│   ├── css/
│   │   └── styles.css   # Stylesheets (responsive, print rules)
│   └── js/
│       └── app.js       # Barcode/QR rendering, validation, chart wiring
├── templates/
│   ├── base.html        # Base template
│   ├── index.html       # Landing page
│   ├── auth/
│   │   ├── login.html   # Unified member/admin/guest sign-in
│   │   └── register.html # Registration (disabled by design)
│   ├── member/
│   │   ├── dashboard.html   # Overview + ID barcode card
│   │   ├── activity.html    # Activity & facility history
│   │   ├── scan.html        # Facility barcode scanner
│   │   ├── expenses.html    # QR receipt expense tracker
│   │   ├── rewards.html     # Voucher QR code
│   │   ├── marketplace.html # Points marketplace + fee credit
│   │   └── coupon_redeem.html # Coupon redemption desk
│   ├── guest/
│   │   ├── dashboard.html   # Guest day-pass portal
│   │   └── quick.html       # Quick guest check-in & purchase
│   └── admin/
│       ├── dashboard.html   # Totals + Chart.js analytics
│       ├── members.html     # Member roster + rewards
│       ├── activity.html    # Activity & check-in management
│       ├── marketplace.html # Coupon catalog management
│       ├── settings.html    # Algorithm settings
│       └── reports.html     # Reports + CSV export
└── tests/
    ├── test_app.py      # Route, auth, validation, and flow tests
    └── test_rewards.py  # Engagement scoring and reward tests
```

## Database Schema

The relational database is normalised (12 tables + a dirty-flag cache table) with foreign keys, `UNIQUE`/`NOT NULL`/`CHECK` constraints, and `ON DELETE CASCADE` for referential integrity. SQLite triggers automatically mark the rewards cache as stale after every write.

### users
- id, username (UNIQUE), password_hash, role (`member`/`admin`), created_at

### members
- id, user_id, full_name, membership_type (`Member`/`Premium`/`VIP`), email, phone, member_code (UNIQUE), yearly_fee, fee_points_applied, fee_paid, join_date

### activities
- id, member_id, activity_type (`visit`/`purchase`/`referral`/`facility`), service_name, transaction_value, guest_count, created_at

### facility_checkins
- id, member_id, guest_id, facility_name, check_in_time, check_out_time, duration_minutes, status (`active`/`completed`)

### guest_ids
- id, guest_code (UNIQUE), guest_name, host_member_id, created_at

### guest_activities
- id, guest_id, activity_type, service_name, transaction_value, created_at

### reward_settings
- id, visit_weight, spending_weight, referral_weight, facility_weight, loyalty_weight, premium_multiplier, vip_multiplier, profit_sharing_pool, points_value_dollars, updated_at

### rewards
- id, member_id, engagement_score, discount_percentage, earned_profit_share, redemption_code (UNIQUE), status (`active`/`redeemed`), created_at

### receipts
- id, receipt_code (UNIQUE), service_name, amount, status (`unscanned`/`scanned`), scanned_by_member, scanned_by_guest, scanned_at, issued_at

### coupons
- id, name, description, category, cost_points, value_amount, facility_name, active, created_at

### member_coupons
- id, member_id, coupon_id, coupon_code (UNIQUE), points_spent, status (`active`/`used`), claimed_at, used_at

### point_transactions
- id, member_id, points_delta, reason, created_at

### rewards_recompute (cache flag)
- id (singleton), pending — set to 1 by 21 SQLite triggers on any write to the scoring tables; the batch engine clears it after recomputing.

## Reward Algorithm

The engagement score is calculated using configurable weightings across five data sources, then scaled by the member's tier:

```
engagement_score =
  (visits            × visit_weight)
  + (total_spending  × spending_weight)     # direct + guest spending
  + (guest_referrals × referral_weight)
  + (facility_minutes × facility_weight)
  + (loyalty_months  × loyalty_weight)      # months since join date
then × tier multiplier (Member ×1.0, Premium ×1.15, VIP ×1.30)
```

Default weights (editable by admins in Settings):

| Factor | Weight |
|--------|--------|
| Visit | 10.0 points |
| Spending | 0.5 points per $ |
| Guest referral | 50.0 points |
| Facility minute | 0.2 points |
| Loyalty month | 5.0 points |

Discount bands:

| Engagement score | Discount |
|------------------|----------|
| 900+ | 20% |
| 500–899 | 15% |
| 250–499 | 10% |
| 100–249 | 5% |
| < 100 | 0% |

### Points & Marketplace

- A member's **points balance** = lifetime engagement score − points spent.
- Points are spent on marketplace coupons (e.g. Gym Day Pass = 40 pts) or converted to a yearly-fee credit at the configured rate (default $0.50 per point).
- All point changes are recorded in the `point_transactions` ledger; overdrafts are rejected server-side.

### Batch Scoring Engine

Rewards are computed by a **single batch pass** (`EngagementEngine.recalculate_all` / `view_all_rewards`) that aggregates all members with a handful of grouped SQL queries over one connection, instead of the legacy per-member N² loop. A SQLite dirty-flag trigger system makes recomputation lazy — page loads stay read-only until data actually changes. The benchmark in `benchmarks/bench_batch.py` measures roughly a **4-order-of-magnitude speedup** with identical scores.

## Testing & Benchmarking

Run the test suite:

```bash
python -m pytest tests/ -q
```

Run the headless behavioural verification (full member/guest/reward lifecycle against a fresh database):

```bash
python verify_behavior.py
```

Run the A/B benchmark (legacy per-member engine vs the batch engine):

```bash
python benchmarks/bench_batch.py
```

Run the endpoint health check — verifies every `url_for` endpoint referenced in templates and `main.py` resolves in the app's URL map (catches a future `BuildError` at the source):

```bash
python check_endpoints.py                      # static check only
python check_endpoints.py --live               # also probe the running server on port 5000
python check_endpoints.py --live http://127.0.0.1:5001
```

If the static check passes but the live probe reports **404s**, the running server is executing stale code and simply needs a restart (e.g. `python main.py` or the preview server).

## Computer Science Concepts

This project demonstrates key IB Computer Science concepts:

- **Databases**: Normalised relational design, SQL queries and joins, foreign keys, constraints, migrations, and SQL triggers
- **Computational Thinking**: Decomposition, abstraction, pattern recognition, algorithm design
- **Algorithms**: Batch engagement scoring (O(N) vs legacy O(N²)), discount-band assignment, hash-map lookups
- **Networks**: Client-server model with HTTP requests, sessions, and cache headers
- **Security**: Password hashing, session management, role-based access control, parameterised SQL (injection-safe)
- **Validation**: Client- and server-side input validation
- **File Processing**: CSV export over HTTP
- **Event-Driven Architecture**: Dirty-flag triggers for lazy recomputation

## License

This project is part of an IB Computer Science Internal Assessment.

## Author

Yashvir Mishr — CS IA 2027
