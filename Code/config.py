"""
================================================================================
 CONFIGURATION MODULE — IB HL CS: System Configuration & Environment Variables
================================================================================
 This tiny module centralises every tunable value in one place.

 KEY IB HL CS CONCEPTS:
  * Separation of concerns: configuration (WHAT values to use) is kept apart
    from logic (WHAT to do with them). Changing an algorithm weight here
    propagates to every file that imports Config — one change, one place
    (maintainability / the DRY principle).
  * Environment variables: `os.environ.get('SECRET_KEY')` reads a value set
    outside the program (e.g. on the deployment server). The app FAILS
    CLOSED when the key is missing or still set to the old public default
    that was once committed to the repository — no public fallback key
    exists. This is how real systems avoid hard-coding secrets into source
    code (security).
  * Named constants instead of "magic numbers": a reader sees
    DEFAULT_VISIT_WEIGHT instead of an unexplained `10.0`.
"""
import os

# Directory containing this file — used to build absolute paths so the app
# works no matter which working directory it is launched from.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    # SECRET_KEY signs the session cookie. Flask uses HMAC to detect
    # tampering, so a leaked key would let an attacker forge sessions.
    # Read from the environment ONLY — there is deliberately NO hardcoded
    # fallback key. Config.validate_config() — called explicitly at app
    # startup — fails closed when the variable is missing or still holds
    # the old publicly-known default (VULN-001).
    SECRET_KEY = os.environ.get('SECRET_KEY')
    # Absolute path to the SQLite database file (single-file persistence).
    # DATABASE_PATH overrides it for deployments that must relocate the DB.
    # On Vercel the filesystem is read-only except /tmp (and ephemeral), so
    # the app defaults to /tmp/fairshare.db there; every other environment
    # keeps the local data/fairshare.db.
    DATABASE = os.environ.get('DATABASE_PATH') or (
        os.path.join('/tmp', 'fairshare.db')
        if os.environ.get('VERCEL') == '1'
        else os.path.join(BASE_DIR, 'data', 'fairshare.db')
    )

    # ------------------------------------------------------------------
    # ALGORITHM WEIGHTS — the "variables" of the engagement-score formula
    # ------------------------------------------------------------------
    # These constants feed the reward algorithm (models.py). Each one scales
    # how much a data source contributes to a member's engagement score:
    #   score = visits*w_v + spending*w_s + referrals*w_r
    #           + facility_mins*w_f + loyalty_months*w_l, then tier-multiplied
    # They are stored in the reward_settings table at first launch, and the
    # admin can later edit them through the web UI (configurability is a
    # stated success criterion).
    DEFAULT_VISIT_WEIGHT = 10.0      # 10 points per visit
    DEFAULT_SPENDING_WEIGHT = 0.5     # 0.5 points per $ spent
    DEFAULT_REFERRAL_WEIGHT = 50.0   # 50 points per guest referral
    DEFAULT_FACILITY_WEIGHT = 0.2     # 0.2 points per facility-minute used
    DEFAULT_LOYALTY_WEIGHT = 5.0      # 5 points per month of membership
    DEFAULT_TIER_MULTIPLIERS = {'Member': 1.0}  # tier system removed
    DEFAULT_PROFIT_POOL = 10000.00   # $10,000 reward pool funding the coupon marketplace
    DEFAULT_POINTS_VALUE_DOLLARS = 0.50  # each point is worth $0.50 against the yearly fee
    DEFAULT_YEARLY_FEE = 1200.00     # standard yearly club membership fee
    DEFAULT_COUPON_VALID_DAYS = 30   # a claimed coupon must be redeemed within 30 days


    @classmethod
    def check_config(cls):
        """Return every configuration problem as a list of messages ([] = healthy).

        Runs the fail-closed SECRET_KEY rules everywhere, plus production-only
        rules when running on Vercel (VERCEL=1 is set automatically by the
        platform): ADMIN_PASSWORD must be set, SEED_DEMO_DATA must be off, and
        the Turso URL/auth-token pair must be configured together.
        """
        problems = []

        if not cls.SECRET_KEY:
            problems.append(
                "SECRET_KEY is not set. Generate one with:\n"
                "    python -c \"import secrets; print(secrets.token_hex(32))\"\n"
                "and export it before starting the app (run.sh / run.bat generate "
                "one automatically for local development)."
            )
        elif cls.SECRET_KEY == _LEGACY_PUBLIC_SECRET:
            problems.append(
                "SECRET_KEY is set to the old publicly-known default "
                "'fairshare_production_secret_key_2026'. This key was committed to "
                "the public repository and must be rotated — generate a fresh value "
                "and export it."
            )

        if os.environ.get('VERCEL') == '1':
            # On Vercel there is no console where a generated password could be
            # printed, so a missing ADMIN_PASSWORD would leave the admin account
            # with a random, unrecoverable password on first boot.
            if not os.environ.get('ADMIN_PASSWORD'):
                problems.append(
                    "ADMIN_PASSWORD is not set. On Vercel the admin password cannot "
                    "be printed anywhere, so without ADMIN_PASSWORD the admin account "
                    "gets a random, unrecoverable password on first boot. Set a strong "
                    "ADMIN_PASSWORD environment variable."
                )

            # Demo members ship with documented passwords (alice/bob/charlie/diana)
            # and must NEVER be seeded into a deployed environment.
            if os.environ.get('SEED_DEMO_DATA') == '1':
                problems.append(
                    "SEED_DEMO_DATA is set to 1. The demo members "
                    "(alice/bob/charlie/diana) have publicly documented passwords "
                    "and must not exist on a deployed site. Remove SEED_DEMO_DATA "
                    "from the Vercel environment variables."
                )

            # The Turso URL and auth token must come as a pair — one without the
            # other means the hosted database fails at runtime with an auth error.
            has_url = bool(os.environ.get('TURSO_URL'))
            has_token = bool(os.environ.get('TURSO_AUTH_TOKEN'))
            if has_url != has_token:
                problems.append(
                    "TURSO_URL and TURSO_AUTH_TOKEN must be set together "
                    f"(TURSO_URL={'set' if has_url else 'missing'}, "
                    f"TURSO_AUTH_TOKEN={'set' if has_token else 'missing'})."
                )

        return problems

    @classmethod
    def validate_config(cls):
        """Fail fast at startup: raise ONE error listing every problem at once.

        Raises RuntimeError with every failing rule in a single message, so a
        misconfigured deployment (e.g. a missing SECRET_KEY on Vercel) produces
        one complete diagnostic instead of crashing on the first problem found.
        """
        problems = cls.check_config()
        if problems:
            raise RuntimeError(
                "FairShare cannot start: configuration problems found:\n"
                + "\n".join(f"  - {p}" for p in problems)
            )


# ---------------------------------------------------------------------------
# STARTUP CONFIG VALIDATION (VULN-001 fix) — fail fast, fail closed
# ---------------------------------------------------------------------------
# The old hardcoded default `fairshare_production_secret_key_2026` was
# committed to the PUBLIC repository, so it is public knowledge. Running
# with it — or with no key at all — would let anyone forge signed session
# cookies (including an admin session).
#
# IMPORT TIME vs STARTUP: `import config` itself must stay side-effect free
# so tooling (benchmarks, DB inspectors, admin scripts) can read settings
# without a key. Instead, the app refuses to START: main.py calls
# Config.validate_config() the moment the Flask app is built (which also
# covers the WSGI/Vercel import path), and serve.py checks first so an
# operator sees a clean error instead of a traceback.
_LEGACY_PUBLIC_SECRET = 'fairshare_production_secret_key_2026'
