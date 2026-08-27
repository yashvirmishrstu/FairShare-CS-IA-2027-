# FairShare

A web application for recreational organisations that rewards members based on their engagement and value generated for the organisation.

## Project Overview

FairShare is designed for country clubs and similar recreational organisations to move away from flat subscription models toward a value-based reward system. The system tracks member visits, guest referrals, facility usage, restaurant spending, and shop purchases to calculate an engagement score that is automatically converted into personalised rewards such as discounts, coupons, and yearly-fee credits.

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

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3 with Flask |
| **Frontend** | HTML, CSS, JavaScript (Jinja2 templates) |
| **Database** | SQLite (single-file, self-seeding on first launch) |
| **Authentication** | Flask sessions with hashed passwords (Werkzeug) |
| **CSRF Protection** | Flask-WTF CSRFProtect |
| **Barcodes / QR** | JsBarcode and QRCode.js (CDN) |
| **Charts** | Chart.js (CDN) |
| **Export** | Python CSV module (in-memory streaming) |
| **Production Server** | Waitress WSGI server |

## Features

### Member Features

- Secure login with hashed passwords (never stored in plain text)
- Personal ID card with a unique scannable barcode (`member_code`) and a print option
- Dashboard showing engagement score, personalised discount, and points balance
- Facility barcode scanning — scan to check in, scan again to check out; session duration tracked automatically
- Activity and facility-session history
- QR receipt scanning to auto-log expenses from admin-issued receipts
- Guest day-pass creation — every guest activity is credited to the hosting member
- Points marketplace — browse and claim coupons with points, view claimed coupons as QR codes
- Coupon redemption desk — scan a claimed coupon's QR to redeem it for a single use (coupons expire after 30 days)
- Credit points toward the yearly membership fee ($0.50 per point by default)
- Redemption QR code (e.g. `FS-RED-XXXXXXXX`) for earned vouchers

### Guest Features (Day-Pass)

- Sign in via a guest pass code or QR
- Facility barcode check-in/check-out with duration tracking
- Record purchases — automatically credited to the host member's rewards
- Scan receipts — also credited to the host member

### Administrator Features

- Secure admin login with role-based access control (RBAC)
- Dashboard with club totals and Chart.js analytics (facility usage trends, peak activity hours, reward-band distribution)
- Member management — add/edit members and manage yearly fees
- Activity logging, manual check-in/check-out, and receipt issuance
- Reward algorithm settings — all five weights, profit pool, and points value
- Coupon marketplace management — add or toggle coupons
- Reports — usage logs and financial reward summaries, exportable as CSV

## Demo Accounts

The database seeds itself on first launch (`data/fairshare.db` is created automatically). No manual setup is required.

**Admin account (secure by default):** the initial `admin` password is never hardcoded. On first launch it is read from the `ADMIN_PASSWORD` environment variable; if that is not set, a strong random password is generated and printed once in the startup log. Set `ADMIN_PASSWORD` in your deployment to choose your own.

**Demo member accounts (opt-in):** the demo members below exist only when `SEED_DEMO_DATA=1` is set before launching (e.g. `SEED_DEMO_DATA=1 ./run.sh`) — the launchers never enable it by default, so a fresh database starts with zero accounts. Public deployments leave it unset and create real members from the admin panel.

| Role | Username | Password |
|------|----------|----------|
| Member | `alice` | `password123` |
| Member | `bob` | `password123` |
| Member | `charlie` | `password123` |
| Member | `diana` | `password123` |

`diana` (Diana Patel, `MBR-1004`) is a rich demo profile — she has visits, purchases, referrals, completed facility sessions, guest day-pass spending, and two claimed marketplace coupons, so every member feature can be explored on her account.

Guests do not have standing accounts — a member creates a guest day-pass from the member dashboard, which generates a unique pass code.

> **Note:** Public self-registration is intentionally disabled. Member accounts must be created by an administrator (security decision — least privilege).

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yashvirmishrstu/FairShare-CS-IA-2027-.git
   cd FairShare-CS-IA-2027-/Code
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application** (pick whichever is convenient — they are identical):
   ```bash
   ./run.sh              # bash / Git Bash / macOS / Linux
   run.bat               # Windows cmd / double-click
   python main.py        # direct (requires SECRET_KEY env var)
   ```
   All three start with debug + auto-reloader on port `5000`, or the first free port if 5000 is busy. Force a port with `./run.sh 8080` (or `run.bat 8080`).

   > The launcher scripts (`run.sh` / `run.bat`) auto-generate a random `SECRET_KEY` for local development if one is not already set.

4. **Open your browser** and navigate to `http://127.0.0.1:5000` (or the printed free port).

The database is created and seeded automatically when the app starts — no `init_db` step or migration command is needed.

### Production Deployment

For production use, run through the Waitress WSGI server:

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
python serve.py
```

This serves on `0.0.0.0:5000` with debug OFF and multi-threaded request handling.

### Deploying to Vercel

The app is also configured for free hosting on **Vercel** (serverless Flask), with a GitHub Actions pipeline that runs the test suite on every push and deploys to production. Because a serverless filesystem is not persistent, the database can be hosted in a SQLite-compatible Turso database (`TURSO_URL`) instead of a local file.

Full setup — importing the repo, the required `SECRET_KEY` / `TURSO_URL` environment variables, persistent storage, and the CI/CD workflow — is documented in [DEPLOY.md](DEPLOY.md).

## Resetting the Demo Database

The database only seeds when it is empty, so to get a clean set of demo accounts back:

1. Stop the running server (Ctrl+C).
2. Delete the database files (the whole `data/` directory is gitignored):
   ```bash
   rm -f data/fairshare.db data/fairshare.db-shm data/fairshare.db-wal
   ```
3. Start the app again — a fresh `data/fairshare.db` is created and re-seeded on first launch.

## Facility Barcode Registry

Facilities are identified by unique barcode codes. Scanning one checks the member (or guest) in; scanning it again checks them out and logs the session duration.

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
├── main.py                  # Flask controller: routes, auth, validation (1,434 lines)
├── models.py                # Business logic: engagement engine, rewards, marketplace (1,125 lines)
├── database.py              # Schema, migrations, seeding, dirty-flag triggers (472 lines)
├── config.py                # Central configuration & algorithm defaults (84 lines)
├── serve.py                 # Production Waitress WSGI entrypoint (54 lines)
├── requirements.txt         # Python dependencies
├── run.sh                   # Launcher: bash / Git Bash / macOS / Linux
├── run.bat                  # Launcher: Windows cmd
├── verify_behavior.py       # Headless end-to-end lifecycle checks
├── check_endpoints.py       # Endpoint health check (static + live stale-server probe)
├── view_db.py               # Database inspection utility
├── .gitignore
│
├── benchmarks/
│   ├── bench_batch.py           # A/B benchmark: legacy vs batch engagement engine
│   └── _legacy_engine_ref.py    # Frozen legacy engine (baseline for comparison)
│
├── data/
│   └── fairshare.db             # SQLite database (auto-created, gitignored)
│
├── static/
│   ├── css/
│   │   └── styles.css           # Stylesheets (responsive, print rules)
│   └── js/
│       └── app.js               # Barcode/QR rendering, validation, chart wiring
│
├── templates/
│   ├── base.html                # Base template (nav, flash messages, CDN scripts)
│   ├── index.html               # Landing page
│   ├── 500.html                 # Custom 500 error page
│   ├── auth/
│   │   ├── login.html           # Unified member / admin / guest sign-in
│   │   └── register.html        # Registration (disabled by design)
│   ├── member/
│   │   ├── dashboard.html       # Overview + ID barcode card
│   │   ├── activity.html        # Activity & facility history
│   │   ├── scan.html            # Facility barcode scanner
│   │   ├── expenses.html        # QR receipt expense tracker
│   │   ├── rewards.html         # Voucher QR code
│   │   ├── marketplace.html     # Points marketplace + fee credit
│   │   └── coupon_redeem.html   # Coupon redemption desk
│   ├── guest/
│   │   ├── dashboard.html       # Guest day-pass portal
│   │   └── quick.html           # Quick guest check-in & purchase
│   └── admin/
│       ├── dashboard.html       # Totals + Chart.js analytics
│       ├── members.html         # Member roster + rewards
│       ├── activity.html        # Activity & check-in management
│       ├── marketplace.html     # Coupon catalog management
│       ├── settings.html        # Algorithm settings
│       └── reports.html         # Reports + CSV export
│
└── tests/
    ├── conftest.py              # Test SECRET_KEY bootstrap
    ├── test_app.py              # Route, auth, validation, and flow tests (835 lines)
    ├── test_rewards.py          # Engagement scoring and marketplace tests (1,044 lines)
    ├── test_security.py         # CSRF, secret key, rate limiting tests (168 lines)
    ├── test_health_checks.py    # Endpoint resolution + full-page render sweep (201 lines)
    ├── test_dev_server.py       # Auto-reloader smoke tests (137 lines)
    └── test_behavior.py         # Full lifecycle subprocess wrapper (53 lines)
```

## Database Schema

The relational database is normalised into **13 tables** (12 entity tables + 1 dirty-flag cache table) with foreign keys, `UNIQUE`/`NOT NULL`/`CHECK` constraints, and `ON DELETE CASCADE` for referential integrity. **21 SQLite triggers** automatically mark the rewards cache as stale after any write to the seven scoring tables.

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | Account credentials | id, username (UNIQUE), password_hash, role (`member`/`admin`) |
| `members` | Member profiles | id, user_id (FK), full_name, member_code (UNIQUE), yearly_fee, fee_paid |
| `activities` | Member activity log | id, member_id (FK), activity_type (`visit`/`purchase`/`referral`/`facility`), transaction_value |
| `facility_checkins` | Facility session tracking | id, member_id (FK), guest_id (FK), facility_name, duration_minutes, status |
| `guest_ids` | Guest day-passes | id, guest_code (UNIQUE), guest_name, host_member_id (FK) |
| `guest_activities` | Guest activity ledger | id, guest_id (FK), activity_type, transaction_value |
| `reward_settings` | Algorithm config (audit trail) | visit/spending/referral/facility/loyalty weights, profit_sharing_pool, points_value_dollars |
| `rewards` | Materialised reward rows | id, member_id (FK), engagement_score, discount_percentage, redemption_code (UNIQUE) |
| `receipts` | QR expense vouchers | id, receipt_code (UNIQUE), amount, status (`unscanned`/`scanned`) |
| `coupons` | Marketplace coupon catalog | id, name, category, cost_points, value_amount, active |
| `member_coupons` | Claimed coupons | id, member_id (FK), coupon_code (UNIQUE), status (`active`/`used`), expires |
| `point_transactions` | Points spend ledger | id, member_id (FK), points_delta, reason |
| `rewards_recompute` | Dirty-flag singleton | id=1, pending (0 or 1) — set by triggers, cleared by batch recompute |
| `login_attempts` | Rate-limit state | username (PK), fail_count, locked_until |

## Reward Algorithm

The engagement score is calculated using configurable weightings across five data sources:

```
engagement_score =
    (visits             × visit_weight)
  + (total_spending     × spending_weight)     # direct + guest spending
  + (guest_referrals    × referral_weight)
  + (facility_minutes   × facility_weight)
  + (loyalty_months     × loyalty_weight)      # months since join date
```

Default weights (editable by admins in Settings):

| Factor | Default Weight |
|--------|---------------|
| Visit | 10.0 points per visit |
| Spending | 0.5 points per dollar |
| Guest referral | 50.0 points per referral |
| Facility minute | 0.2 points per minute |
| Loyalty month | 5.0 points per month |

### Discount Bands

| Engagement Score | Discount |
|-----------------|----------|
| 900+ | 20% |
| 500 – 899 | 15% |
| 250 – 499 | 10% |
| 100 – 249 | 5% |
| < 100 | 0% |

### Points & Marketplace

- A member's **points balance** = lifetime engagement score − points spent.
- Points are spent on marketplace coupons (e.g. Gym Day Pass = 40 pts) or converted to a yearly-fee credit at the configured rate (default $0.50 per point).
- Claimed coupons expire after 30 days and can only be redeemed once.
- All point changes are recorded in the `point_transactions` ledger; overdrafts are rejected server-side.

### Batch Scoring Engine

Rewards are computed by a **single batch pass** (`EngagementEngine.recalculate_all` / `view_all_rewards`) that aggregates all members with a handful of grouped SQL queries over one connection, instead of the legacy per-member O(N²) loop. A SQLite dirty-flag trigger system makes recomputation **lazy** — page loads stay read-only until data actually changes. The benchmark in `benchmarks/bench_batch.py` measures roughly a **4-order-of-magnitude speedup** with identical scores.

## Security

| Measure | Implementation |
|---------|---------------|
| **Password hashing** | Werkzeug `generate_password_hash` / `check_password_hash` — never plaintext |
| **Session management** | HMAC-signed cookies via Flask; `session.clear()` before login prevents session fixation |
| **Fail-closed SECRET_KEY** | No hardcoded fallback; the old publicly-committed key is rejected at import time |
| **CSRF protection** | Flask-WTF CSRFProtect on every state-changing POST |
| **Rate limiting** | Exponential-backoff lockout after 5 failed login attempts (DB-persisted, survives restarts) |
| **SQL injection prevention** | Parameterised queries everywhere — no string interpolation |
| **Role-based access control** | `@admin_required` / `@login_required` / `@guest_required` decorators |
| **Atomic deduplication** | `UPDATE ... WHERE status='unscanned'` prevents double-scan of receipts and coupons |
| **Input validation** | Server-side validation on every route; `math.isfinite()` and non-negative checks |
| **Cache control** | `no-store` on HTML/API responses; `public, max-age=3600` only for static assets |

## Testing & Benchmarking

Run the full test suite:
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

Run the endpoint health check:
```bash
python check_endpoints.py                      # static check only
python check_endpoints.py --live               # also probe the running server on port 5000
python check_endpoints.py --live http://127.0.0.1:5001
```

### Test Coverage

| Test File | Focus | Lines |
|-----------|-------|-------|
| `test_app.py` | Routes, auth, validation, full user flows | 835 |
| `test_rewards.py` | Engagement scoring, discount bands, marketplace, fee credits | 1,044 |
| `test_security.py` | CSRF enforcement, secret-key hardening, rate limiting | 168 |
| `test_health_checks.py` | Endpoint resolution, full-page render sweep | 201 |
| `test_dev_server.py` | Auto-reloader configuration smoke tests | 137 |
| `test_behavior.py` | Full lifecycle verification (subprocess) | 53 |

## Success Criteria

1. ✅ Secure login for members and administrators with hashed passwords
2. ✅ Relational database storage without data duplication
3. ✅ Recording of member visits, facility usage, and purchases with timestamps
4. ✅ Automatic engagement score calculation based on configurable factors
5. ✅ Automatic personalised discount generation based on engagement score
6. ✅ Member dashboard displaying reward status, engagement score, and discounts
7. ✅ Scanning a unique user ID barcode for facility check-in/check-out
8. ✅ Facility usage tracking with duration calculation
9. ✅ Guest ID creation for tracking guest visits and spending
10. ✅ Admin control panel for algorithm settings and member management
11. ✅ Redemption QR code / coupon code generation for discounts
12. ✅ Responsive UI for mobile, tablet, and desktop
13. ✅ Fast page loading (under 2–3 seconds) with asset caching
14. ✅ Admin charts showing usage trends, peak hours, and reward distribution
15. ✅ CSV export for member usage logs and financial summaries
16. ✅ Client- and server-side validation for data integrity and security

## Computer Science Concepts

This project demonstrates key IB Computer Science HL concepts:

- **Databases**: Normalised relational design, SQL queries and joins, foreign keys, constraints, schema migrations, and SQL triggers
- **Computational Thinking**: Decomposition (MVC), abstraction (service classes), pattern recognition, algorithm design
- **Algorithms**: Batch engagement scoring (O(N) vs legacy O(N²)), discount-band assignment, hash-map lookups
- **Data Structures**: Dictionaries as hash maps for O(1) member lookups, in-memory StringIO buffers
- **Networks**: Client-server model with HTTP requests, sessions, and cache headers
- **Security**: Password hashing, session management, RBAC, CSRF, rate limiting, parameterised SQL
- **OOP**: Encapsulation (service classes), static/class methods, higher-order functions (decorators)
- **Validation**: Client- and server-side input validation, defensive programming
- **File Processing**: CSV export over HTTP with streaming in-memory buffers
- **Event-Driven Architecture**: Dirty-flag triggers for lazy recomputation

## License

This project is part of an IB Computer Science Internal Assessment.

## Author

Yashvir Mishr — CS IA 2027
