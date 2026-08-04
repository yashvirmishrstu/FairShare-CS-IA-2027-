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
    # fallback key. The module-level check below fails closed at import
    # time when the variable is missing or still holds the old
    # publicly-known default (VULN-001).
    SECRET_KEY = os.environ.get('SECRET_KEY')
    # Absolute path to the SQLite database file (single-file persistence).
    DATABASE = os.path.join(BASE_DIR, 'data', 'fairshare.db')

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


# ---------------------------------------------------------------------------
# FAIL-CLOSED SECRET_KEY (VULN-001 fix)
# ---------------------------------------------------------------------------
# The old hardcoded default `fairshare_production_secret_key_2026` was
# committed to the PUBLIC repository, so it is public knowledge. Running
# with it — or with no key at all — would let anyone forge signed session
# cookies (including an admin session). Refuse to start instead of silently
# serving with a predictable signing key.
_LEGACY_PUBLIC_SECRET = 'fairshare_production_secret_key_2026'

if not Config.SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Generate one with:\n"
        "    python -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "and export it before starting the app (run.sh / run.bat generate "
        "one automatically for local development)."
    )
if Config.SECRET_KEY == _LEGACY_PUBLIC_SECRET:
    raise RuntimeError(
        "SECRET_KEY is set to the old publicly-known default "
        "'fairshare_production_secret_key_2026'. This key was committed to "
        "the public repository and must be rotated — generate a fresh value "
        "and export it."
    )
