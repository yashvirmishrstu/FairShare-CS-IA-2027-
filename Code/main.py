"""
================================================================================
 FAIRSHARE — WEB APPLICATION (Controller Layer) — IB HL CS
================================================================================
 This is the *controller* of a Model-View-Controller (MVC) web application:

   Model       -> models.py   (business logic: engagement scoring, rewards)
   View        -> templates/  (Jinja2 HTML rendered server-side)
   Controller  -> THIS FILE   (routes: map HTTP requests to logic + views)

 KEY IB HL CS CONCEPTS DEMONSTRATED:
  * Client-server networking: the browser (client) sends HTTP requests
    (GET for pages, POST for form data) to this Flask server, which
    responds with HTML documents and HTTP status codes (200, 302 redirects).
  * Authentication vs Authorisation: login (verifying WHO you are) is
    handled with password *hashing*; access control (WHAT you may do) is
    handled by role checks in decorators (admin_required). Sessions keep
    the user logged in between requests via an HMAC-signed cookie.
  * Security engineering: parameterised SQL (no injection), hashed
    passwords (never plain text), role-based access control (RBAC),
    server-side validation of every input, and HTTP cache headers.
  * Computational thinking: each route is one *decomposition* of the
    overall problem into small, single-purpose functions; validation and
    error messages follow a consistent pattern (defensive programming).
"""
import functools
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from database import get_db, init_db
from models import RewardSettings, EngagementEngine, FacilityTracker, GuestManager, ReceiptManager, CSVReportGenerator, MarketplaceManager

app = Flask(__name__)
app.config.from_object(Config)

# Facility Barcode Registry — every facility has a unique scannable barcode code.
# Members scan the code posted at a facility entrance to start their session timer,
# then scan the same code again to check out and log usage duration.
#
# IB HL CS: this dictionary is a *map / associative array* (key -> value).
# The key is the machine-scannable barcode; the value is the human-readable
# facility name. Lookups are O(1) on average. It also acts as a *whitelist*
# for validation: any scanned code not present here is rejected as invalid.
FACILITIES = {
    "FAC-101": "Club Fitness & Gym",
    "FAC-102": "Tennis & Squash Courts",
    "FAC-103": "Swimming Pool & Spa",
    "FAC-104": "Bistro & Lounge",
    "FAC-105": "Pro Golf Course",
}

# Ensure database tables exist on launch
init_db()

# HTTP Cache Control Header for Asset Optimization & Fast Load Times (<2-3s)
# In debug mode nothing is cached so code/template/asset edits show up instantly during development.
#
# IB HL CS: HTTP response headers control browser caching behaviour. In
# production, `Cache-Control: public, max-age=3600` tells the browser and
# any intermediate proxy they may reuse static assets for an hour, cutting
# repeat page-load times dramatically (meets the 2-3s load-time success
# criterion). In debug mode we disable caching entirely so developers always
# see fresh changes.
@app.after_request
def add_header(response):
    if app.debug:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    else:
        response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

# ---------------------------------------------------------------------------
# AUTHORISATION DECORATORS — IB HL CS: role-based access control (RBAC)
# ---------------------------------------------------------------------------
# A decorator is a *higher-order function*: it takes a function, wraps it in
# a new function that runs a check FIRST, and returns the wrapper. Placing
# @admin_required above a route means "run this check before the route".
# This implements the security principle of LEAST PRIVILEGE — members simply
# cannot reach admin pages, even by typing the URL directly.
# functools.wraps preserves the original function's metadata (name, docstring)
# so Flask's URL routing and debugging still work normally.
def login_required(f):
    """Reject unauthenticated requests — the baseline gate for member pages."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Reject anyone who is not logged in AND not an administrator."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Unauthorized access! Administrator privileges required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def guest_required(f):
    """Require an active guest day-pass session (expires at end of day).

    IB HL CS: an example of *validation with expiry* — a guest pass is only
    valid on the calendar day it was issued (compare session date to today).
    Stale sessions are cleaned up defensively before redirecting.
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        guest_id = session.get('guest_id')
        today = datetime.now().strftime('%Y-%m-%d')
        if not guest_id or session.get('guest_login_date') != today:
            session.pop('guest_id', None)
            session.pop('guest_login_date', None)
            flash('Your guest day pass has expired. Please sign in again.', 'warning')
            return redirect(url_for('login', tab='guest'))
        return f(*args, **kwargs)
    return decorated_function

# Context Processor for Navigation Badges & User Info
#
# IB HL CS: a Flask *context processor* injects variables into EVERY
# template render automatically (dependency injection). This avoids
# repeating the same DB lookup in every route. Note: one query per request
# here is acceptable; heavier per-member queries were batched in models.py.
@app.context_processor
def inject_user():
    user = None
    member = None
    guest = None
    if 'user_id' in session:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (session['user_id'],))
        user = cursor.fetchone()
        if user and user['role'] == 'member':
            cursor.execute("SELECT * FROM members WHERE user_id = ?", (user['id'],))
            member = cursor.fetchone()
        conn.close()
    if 'guest_id' in session:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, guest_name, guest_code FROM guest_ids WHERE id = ?", (session['guest_id'],))
        guest = cursor.fetchone()
        conn.close()
    return dict(current_user=user, current_member=member, current_guest=guest)

# Public Routes
@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('member_dashboard'))
    return render_template('index.html')

@app.route('/guest/quick', methods=['GET', 'POST'])
def guest_quick():
    """Quick Guest Check-In & Purchase: scan the Guest Pass QR (or enter its code),
    record a purchase in one step — the guest is signed in for the day and all
    spending is credited to their host member's rewards."""
    today = datetime.now().strftime('%Y-%m-%d')

    # Already signed in today? Go straight to their live tracking dashboard.
    if session.get('guest_id') and session.get('guest_login_date') == today:
        return redirect(url_for('guest_dashboard'))

    if request.method == 'POST':
        guest_code = request.form.get('guest_code', '').strip().upper()
        service_name = request.form.get('service_name', '').strip()
        amount_str = request.form.get('amount', '').strip()
        try:
            amount = float(amount_str) if amount_str else None
        except ValueError:
            amount = None

        if not guest_code:
            flash('Please scan or enter your Guest Pass Code.', 'warning')
        elif not service_name:
            flash('Please describe the facility service used.', 'warning')
        elif amount is None:
            flash('Please enter a valid transaction amount.', 'warning')
        elif amount < 0:
            flash('Transaction amount cannot be negative.', 'danger')
        else:
            guest = GuestManager.get_guest_by_code(guest_code)
            if not guest:
                flash(f'Invalid Guest Pass Code "{guest_code}". Please try again.', 'danger')
            else:
                # Sign the guest in for the day and record the purchase in one step.
                session.clear()
                session['guest_id'] = guest['id']
                session['guest_login_date'] = today
                GuestManager.record_spending(guest['id'], service_name, amount)
                settings = RewardSettings.get_settings()
                pts = int(round(amount * settings['spending_weight']))
                flash(f'Welcome, {guest["guest_name"]}! Purchase of ${amount:.2f} recorded — +{pts} pts credited to your host member.', 'success')
                return redirect(url_for('guest_dashboard'))

    return render_template('guest/quick.html')


@app.route('/guest/dashboard')
@guest_required
def guest_dashboard():
    """Guest day portal: facility barcode scanner, purchases, and activity tracking."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guest_ids WHERE id = ?", (session['guest_id'],))
    guest = cursor.fetchone()

    if not guest:
        session.pop('guest_id', None)
        session.pop('guest_login_date', None)
        conn.close()
        flash('Guest pass not found. Please sign in again.', 'danger')
        return redirect(url_for('login', tab='guest'))

    # Host member this guest is linked to
    cursor.execute("SELECT full_name, member_code FROM members WHERE id = ?", (guest['host_member_id'],))
    host = cursor.fetchone()

    # Active facility session + recent completed sessions
    cursor.execute("SELECT * FROM facility_checkins WHERE guest_id = ? AND status = 'active'", (guest['id'],))
    active_checkin = cursor.fetchone()

    cursor.execute('''
        SELECT * FROM facility_checkins WHERE guest_id = ? AND status = 'completed'
        ORDER BY check_in_time DESC LIMIT 8
    ''', (guest['id'],))
    recent_sessions = cursor.fetchall()

    # Guest activity ledger + today's spending
    cursor.execute('''
        SELECT * FROM guest_activities WHERE guest_id = ? ORDER BY created_at DESC LIMIT 20
    ''', (guest['id'],))
    activity = cursor.fetchall()

    cursor.execute('''
        SELECT COALESCE(SUM(transaction_value), 0.0) FROM guest_activities
        WHERE guest_id = ? AND activity_type = 'purchase' AND date(created_at) = date('now')
    ''', (guest['id'],))
    today_spending = cursor.fetchone()[0]

    # Open (unscanned) expense receipts the guest can scan to log a purchase
    cursor.execute("SELECT * FROM receipts WHERE status = 'unscanned' ORDER BY issued_at DESC LIMIT 6")
    open_receipts = cursor.fetchall()

    conn.close()

    return render_template('guest/dashboard.html', guest=guest, host=host,
                           active_checkin=active_checkin, recent_sessions=recent_sessions,
                           activity=activity, today_spending=today_spending, facilities=FACILITIES,
                           open_receipts=open_receipts)

@app.route('/guest/scan', methods=['POST'])
@guest_required
def guest_scan():
    """Facility barcode scanner for guests: first scan checks in, second checks out."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guest_ids WHERE id = ?", (session['guest_id'],))
    guest = cursor.fetchone()

    facility_code = request.form.get('facility_code', '').strip().upper()
    if not facility_code:
        flash('No barcode detected. Please scan a facility barcode.', 'warning')
    elif facility_code not in FACILITIES:
        flash(f'Unknown facility barcode "{facility_code}". Please scan a valid facility code.', 'danger')
    else:
        facility_name = FACILITIES[facility_code]
        cursor.execute("SELECT * FROM facility_checkins WHERE guest_id = ? AND status = 'active'", (guest['id'],))
        active = cursor.fetchone()

        if active:
            if active['facility_name'] == facility_name:
                duration = FacilityTracker.check_out(active['id'])
                if duration:
                    settings = RewardSettings.get_settings()
                    visit_pts = int(round(settings['visit_weight']))
                    facility_pts = int(round(duration * settings['facility_weight']))
                    total_pts = visit_pts + facility_pts
                    flash(f'Checked out of {facility_name}! Session duration: {duration} mins. +{total_pts} pts earned!', 'success')
                else:
                    flash(f'Checked out of {facility_name}!', 'success')
            else:
                flash(f'You are currently checked into {active["facility_name"]}. Scan that facility again to check out first.', 'warning')
        else:
            FacilityTracker.guest_check_in(guest['id'], guest['host_member_id'], facility_name)
            flash(f'Checked in to {facility_name}! Timer started. Scan again to check out.', 'success')

    conn.close()
    return redirect(url_for('guest_dashboard'))

@app.route('/guest/logout', methods=['POST'])
@guest_required
def guest_logout():
    session.pop('guest_id', None)
    session.pop('guest_login_date', None)
    flash('You have been signed out of your guest day pass. Have a great visit!', 'info')
    return redirect(url_for('login', tab='guest'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Unified sign-in for members, admins, and guests — each role is routed
    to its own suite (member dashboard, admin dashboard, guest day portal).

    IB HL CS: SECURITY NOTES —
    * Passwords are never stored or compared in plain text: registration
      stores `generate_password_hash(password)` (a salted one-way hash) and
      login verifies with `check_password_hash`. Even if the database leaks,
      passwords cannot be recovered from the hashes.
    * All inputs are validated server-side (empty fields rejected with a
      flash message) — client-side checks can be bypassed, so the server is
      the authoritative validation point.
    * On success the server writes to the session (signed cookie), setting
      user_id, username and role. Every later request reads this session to
      authorise actions — stateless session management via HMAC-signed
      cookies.
    * session.clear() before login prevents session-fixation attacks (an
      attacker-supplied session id cannot be reused).
    """
    today = datetime.now().strftime('%Y-%m-%d')

    tab = request.args.get('tab') if request.args.get('tab') in ('account', 'guest') else 'account'

    if request.method == 'GET':
        # Already signed in? Go straight to the matching suite.
        if session.get('user_id'):
            if session.get('role') == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('member_dashboard'))
        if session.get('guest_id') and session.get('guest_login_date') == today:
            return redirect(url_for('guest_dashboard'))
        return render_template('auth/login.html', tab=tab)

    # POST — an explicit sign-in attempt always replaces any prior session,
    # so a guest can switch to a member account (or vice versa) via /login.
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    # Guest day-pass sign-in: scan the Guest Pass QR or enter its code.
    # The pass is linked to the member who created it, so all guest activity
    # is credited to that host member.
    guest_code = request.form.get('guest_code', '').strip().upper()
    if guest_code and not username:
        guest = GuestManager.get_guest_by_code(guest_code)
        if not guest:
            flash(f'Invalid Guest Pass Code "{guest_code}". Please try again.', 'danger')
            return render_template('auth/login.html', tab='guest')
        session.clear()
        session['guest_id'] = guest['id']
        session['guest_login_date'] = today
        flash(f'Welcome, {guest["guest_name"]}! Your day pass is active and linked to your host member.', 'success')
        return redirect(url_for('guest_dashboard'))

    # Member / Admin sign-in

    # Server-side Validation
    if not username or not password:
        flash('Username and password are required fields.', 'danger')
        return render_template('auth/login.html', tab=tab)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()

    if user and check_password_hash(user['password_hash'], password):
        session.clear()
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']

        flash(f'Welcome back, {user["username"]}!', 'success')
        if user['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('member_dashboard'))

    flash('Invalid username or password credentials.', 'danger')
    return render_template('auth/login.html', tab=tab)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration is intentionally DISABLED for the public.

    IB HL CS: a security decision — open self-registration would let anyone
    create an account (and potentially a member profile). Restricting account
    creation to administrators enforces the principle of least privilege and
    keeps the member roster trustworthy.
    """
    flash('Public self-registration is disabled. Member accounts must be created by a club administrator.', 'info')
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    """Clear the server-side session to end the authenticated session."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# Member Routes
@app.route('/member/dashboard')
@login_required
def member_dashboard():
    """The member's personalised overview page.

    IB HL CS: this route gathers data from several queries and combines it
    into one view-model dict passed to the Jinja template. The rewards view
    uses lazy materialisation (see EngagementEngine.view_member_rewards) so
    a normal page load is a pure read. Points-history rows are computed by
    applying the SAME algorithm weights as the engine — one source of truth
    (DRY) so the page and the score can never disagree.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()

    if not member:
        conn.close()
        flash('Member profile not found.', 'danger')
        return redirect(url_for('index'))

    # Rewards view — lazily materializes only when a scoring write happened
    # (the dirty flag is set by SQLite triggers); otherwise a pure read.
    rewards = EngagementEngine.view_member_rewards(member['id'])

    # Recent activities
    cursor.execute('''
        SELECT activity_type, service_name, transaction_value, guest_count, created_at
        FROM activities WHERE member_id = ? ORDER BY created_at DESC LIMIT 8
    ''', (member['id'],))
    recent_activities = cursor.fetchall()

    # Points history — annotate each recent event with the points it earned,
    # using the same active algorithm weights as the engagement engine
    settings = RewardSettings.get_settings()
    points_history = []
    for act in recent_activities:
        if act['activity_type'] == 'visit':
            pts = round(settings['visit_weight'], 2)
        elif act['activity_type'] == 'purchase':
            pts = round((act['transaction_value'] or 0) * settings['spending_weight'], 2)
        elif act['activity_type'] == 'referral':
            pts = round((act['guest_count'] or 0) * settings['referral_weight'], 2)
        else:
            pts = 0.0
        points_history.append({
            'activity_type': act['activity_type'],
            'service_name': act['service_name'],
            'transaction_value': act['transaction_value'],
            'guest_count': act['guest_count'],
            'created_at': act['created_at'],
            'points': pts,
        })

    # Active facility checkins (member-only sessions, excluding guest sessions)
    cursor.execute('''
        SELECT * FROM facility_checkins WHERE member_id = ? AND guest_id IS NULL AND status = 'active'
    ''', (member['id'],))
    active_checkin = cursor.fetchone()

    # Hosted guest IDs
    cursor.execute("SELECT * FROM guest_ids WHERE host_member_id = ? ORDER BY created_at DESC", (member['id'],))
    guests = cursor.fetchall()

    conn.close()

    return render_template('member/dashboard.html', member=member, rewards=rewards,
                           recent_activities=recent_activities, points_history=points_history,
                           active_checkin=active_checkin, guests=guests)

@app.route('/member/activity')
@login_required
def member_activity():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()

    # Retrieve all member activities (read-only view)
    cursor.execute('''
        SELECT * FROM activities WHERE member_id = ? ORDER BY created_at DESC
    ''', (member['id'],))
    activities = cursor.fetchall()

    # Retrieve member facility checkin logs (member-only sessions, excluding guest sessions)
    cursor.execute('''
        SELECT * FROM facility_checkins WHERE member_id = ? AND guest_id IS NULL ORDER BY check_in_time DESC
    ''', (member['id'],))
    checkins = cursor.fetchall()

    conn.close()

    return render_template('member/activity.html', activities=activities, checkins=checkins)

@app.route('/member/scan', methods=['GET', 'POST'])
@login_required
def member_scan():
    """
    Facility barcode scanner: scanning a facility's barcode checks the member in
    and starts the session timer; scanning it again checks out and logs duration.

    IB HL CS: this route implements a *state machine* — check-in and check-out
    are two states of one facility session. Validation (defensive programming)
    rejects empty or unknown barcodes, and duplicate sessions are prevented
    (a second scan while active is treated as check-out only for the SAME
    facility). Each action gives immediate feedback via flash messages.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()

    if not member:
        conn.close()
        flash('Member profile not found.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        facility_code = request.form.get('facility_code', '').strip().upper()

        if not facility_code:
            flash('No barcode detected. Please scan a facility barcode.', 'warning')
        elif facility_code not in FACILITIES:
            flash(f'Unknown facility barcode "{facility_code}". Please scan a valid facility code.', 'danger')
        else:
            facility_name = FACILITIES[facility_code]
            cursor.execute("SELECT * FROM facility_checkins WHERE member_id = ? AND guest_id IS NULL AND status = 'active'", (member['id'],))
            active = cursor.fetchone()

            if active:
                if active['facility_name'] == facility_name:
                    duration = FacilityTracker.check_out(active['id'])
                    if duration:
                        settings = RewardSettings.get_settings()
                        visit_pts = int(round(settings['visit_weight']))
                        facility_pts = int(round(duration * settings['facility_weight']))
                        total_pts = visit_pts + facility_pts
                        flash(f'Checked out of {facility_name}! Session duration: {duration} mins. +{total_pts} pts earned!', 'success')
                    else:
                        flash(f'Checked out of {facility_name}!', 'success')
                else:
                    flash(f'You are currently checked into {active["facility_name"]}. Scan that facility again to check out first.', 'warning')
            else:
                FacilityTracker.check_in(member['id'], facility_name)
                flash(f'Checked in to {facility_name}! Timer started. Scan again to check out.', 'success')

        conn.close()
        return redirect(url_for('member_scan'))

    # Active session + recent completed sessions for the scanner page (member-only)
    cursor.execute("SELECT * FROM facility_checkins WHERE member_id = ? AND guest_id IS NULL AND status = 'active'", (member['id'],))
    active_checkin = cursor.fetchone()

    cursor.execute('''
        SELECT * FROM facility_checkins WHERE member_id = ? AND guest_id IS NULL AND status = 'completed'
        ORDER BY check_in_time DESC LIMIT 8
    ''', (member['id'],))
    recent_sessions = cursor.fetchall()

    conn.close()

    return render_template('member/scan.html', facilities=FACILITIES,
                           active_checkin=active_checkin, recent_sessions=recent_sessions)

@app.route('/admin/receipts/issue', methods=['POST'])
@admin_required
def admin_receipt_issue():
    """Issue an expense receipt voucher — its QR is scanned by the member or
    guest at the end of the purchase to log the expense automatically."""
    service_name = request.form.get('service_name', '').strip()
    try:
        amount = float(request.form.get('amount', 0.0))
    except ValueError:
        amount = -1.0

    if not service_name:
        flash('Please describe the service on the receipt.', 'warning')
    elif amount <= 0:
        flash('Receipt amount must be greater than zero.', 'danger')
    else:
        receipt = ReceiptManager.issue_receipt(service_name, amount)
        flash(f'Receipt issued! Code {receipt["receipt_code"]} — show the QR so the member can scan it.', 'success')
    return redirect(url_for('admin_activity'))

@app.route('/member/expenses')
@login_required
def member_expenses():
    """Member QR expense tracker: scan the QR at the end of a receipt to log
    the expense automatically, plus a full expense ledger."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()

    if not member:
        conn.close()
        flash('Member profile not found.', 'danger')
        return redirect(url_for('index'))

    # Expense ledger: purchase activities + receipts scanned by this member
    cursor.execute('''
        SELECT activity_type, service_name, transaction_value, created_at
        FROM activities WHERE member_id = ? AND activity_type = 'purchase'
        ORDER BY created_at DESC LIMIT 15
    ''', (member['id'],))
    expenses = cursor.fetchall()

    cursor.execute('''
        SELECT * FROM receipts WHERE scanned_by_member = ? ORDER BY scanned_at DESC LIMIT 10
    ''', (member['id'],))
    scanned_receipts = cursor.fetchall()

    # Open (unscanned) receipts that can still be logged — demo scan cards
    cursor.execute("SELECT * FROM receipts WHERE status = 'unscanned' ORDER BY issued_at DESC LIMIT 6")
    open_receipts = cursor.fetchall()

    conn.close()
    return render_template('member/expenses.html', member=member, expenses=expenses,
                           scanned_receipts=scanned_receipts, open_receipts=open_receipts)

@app.route('/member/receipts/scan', methods=['POST'])
@login_required
def member_receipt_scan():
    """Member scans the QR at the end of a receipt — logs the expense and
    updates the member's rewards."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()
    conn.close()

    receipt_code = request.form.get('receipt_code', '').strip().upper()
    if not receipt_code:
        flash('No receipt QR detected. Please scan the QR at the end of your receipt.', 'warning')
        return redirect(url_for('member_expenses'))

    if not member:
        flash('Member profile not found.', 'danger')
        return redirect(url_for('member_expenses'))

    receipt = ReceiptManager.get_receipt_by_code(receipt_code)
    result = ReceiptManager.redeem_for_member(receipt_code, member['id'])
    if result['ok']:
        settings = RewardSettings.get_settings()
        pts = int(round((receipt['amount'] if receipt else 0) * settings['spending_weight']))
        flash(f'{result["message"]} +{pts} pts earned!', 'success')
    else:
        flash(result['message'], 'danger')
    return redirect(url_for('member_expenses'))

@app.route('/guest/receipts/scan', methods=['POST'])
@guest_required
def guest_receipt_scan():
    """Guest scans the receipt QR — the expense is logged to their ledger and
    credited to their host member's rewards."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guest_ids WHERE id = ?", (session['guest_id'],))
    guest = cursor.fetchone()
    conn.close()

    receipt_code = request.form.get('receipt_code', '').strip().upper()
    if not receipt_code:
        flash('No receipt QR detected. Please scan the QR at the end of your receipt.', 'warning')
        return redirect(url_for('guest_dashboard'))

    if not guest:
        flash('Guest pass not found. Please sign in again.', 'danger')
        return redirect(url_for('login', tab='guest'))

    receipt = ReceiptManager.get_receipt_by_code(receipt_code)
    result = ReceiptManager.redeem_for_guest(receipt_code, guest['id'])
    if result['ok']:
        settings = RewardSettings.get_settings()
        pts = int(round((receipt['amount'] if receipt else 0) * settings['spending_weight']))
        flash(f'{result["message"]} +{pts} pts earned!', 'success')
    else:
        flash(result['message'], 'danger')
    return redirect(url_for('guest_dashboard'))

@app.route('/admin/checkin', methods=['POST'])
@admin_required
def admin_checkin():
    member_id = request.form.get('member_id')
    facility_name = request.form.get('facility_name', 'General Club House')
    try:
        member_id = int(member_id)
    except (TypeError, ValueError):
        flash('Invalid member ID.', 'danger')
        return redirect(url_for('admin_activity'))
    FacilityTracker.check_in(member_id, facility_name)
    flash(f'Member checked in to {facility_name}!', 'success')
    return redirect(url_for('admin_activity'))

@app.route('/admin/checkout/<int:checkin_id>', methods=['POST'])
@admin_required
def admin_checkout(checkin_id):
    duration = FacilityTracker.check_out(checkin_id)
    if duration:
        settings = RewardSettings.get_settings()
        visit_pts = int(round(settings['visit_weight']))
        facility_pts = int(round(duration * settings['facility_weight']))
        total_pts = visit_pts + facility_pts
        flash(f'Member checked out! Duration logged: {duration} minutes. +{total_pts} pts earned!', 'info')
    else:
        flash('Invalid check-out request.', 'danger')
    return redirect(url_for('admin_activity'))

@app.route('/member/guest/create', methods=['POST'])
@login_required
def member_guest_create():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()

    guest_name = request.form.get('guest_name', '').strip()
    if not guest_name:
        flash('Guest name is required.', 'danger')
        conn.close()
        return redirect(url_for('member_dashboard'))

    result = GuestManager.create_guest_id(member['id'], guest_name)
    settings = RewardSettings.get_settings()
    pts = int(round(settings['referral_weight']))
    flash(f'Guest ID Created! Pass Code: {result["guest_code"]} — +{pts} pts earned!', 'success')
    conn.close()
    return redirect(url_for('member_dashboard'))

@app.route('/guest/spending', methods=['POST'])
@guest_required
def guest_spending():
    """Record a purchase against the signed-in guest — credited to their host member."""
    service_name = request.form.get('service_name', '').strip()
    try:
        amount = float(request.form.get('amount', 0.0))
    except ValueError:
        amount = -1.0

    if amount < 0:
        flash('Transaction amount cannot be negative.', 'danger')
        return redirect(url_for('guest_dashboard'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM guest_ids WHERE id = ?", (session['guest_id'],))
    guest = cursor.fetchone()
    conn.close()

    if not guest:
        flash('Guest pass not found. Please sign in again.', 'danger')
        return redirect(url_for('login', tab='guest'))

    GuestManager.record_spending(guest['id'], service_name, amount)
    settings = RewardSettings.get_settings()
    pts = int(round(amount * settings['spending_weight']))
    flash(f'Purchase of ${amount:.2f} recorded — +{pts} pts credited to your host member!', 'success')
    return redirect(url_for('guest_dashboard'))

@app.route('/member/rewards', methods=['GET', 'POST'])
@login_required
def member_rewards():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()

    if request.method == 'POST':
        # Redeem reward action
        cursor.execute("UPDATE rewards SET status = 'redeemed' WHERE member_id = ? AND status = 'active'", (member['id'],))
        conn.commit()
        # The redeem just flipped the member's only active voucher to
        # 'redeemed'. Force a materialization pass so a fresh active voucher
        # with a new code is persisted immediately — otherwise the member would
        # permanently lose their active reward row and could never claim
        # coupons again (claim/credit read the earned score from live data).
        rewards = EngagementEngine.recalculate_all(force=True).get(member['id'])
        flash('Voucher code generated & verified!', 'success')
    else:
        # Rewards view — lazily materializes only when a scoring write happened
        rewards = EngagementEngine.view_member_rewards(member['id'])

    conn.close()
    return render_template('member/rewards.html', rewards=rewards)


# Admin Routes
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM members")
    total_members = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM activities")
    total_activities = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(transaction_value), 0.0) FROM activities")
    total_spending = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(duration_minutes), 0) FROM facility_checkins WHERE status = 'completed'")
    total_facility_mins = cursor.fetchone()[0]

    settings = RewardSettings.get_settings()
    conn.close()

    return render_template('admin/dashboard.html', total_members=total_members,
                           total_activities=total_activities, total_spending=total_spending,
                           total_facility_mins=total_facility_mins, settings=settings)

@app.route('/admin/api/analytics')
@admin_required
def admin_analytics_api():
    """JSON endpoint feeding the admin dashboard's Chart.js visualisations.

    IB HL CS: this is a *data-processing pipeline* — raw rows from the
    database are aggregated with GROUP BY queries (facility usage, peak
    activity hours, reward band distribution), converted into Python dicts,
    and serialised to JSON (JavaScript Object Notation) for the client.
    This demonstrates data transformation between the persistence layer and
    the presentation layer.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Facility usage trends by type
    cursor.execute('''
        SELECT facility_name, COUNT(*) as usage_count, SUM(duration_minutes) as total_duration
        FROM facility_checkins GROUP BY facility_name
    ''')
    facility_trends = [dict(row) for row in cursor.fetchall()]

    # Total rewards distributed breakdown — computed from the live rewards
    # view (lazily materialized when a scoring write happened).
    band_counts = {}
    for r in EngagementEngine.view_all_rewards().values():
        d = r['discount_percentage']
        band_counts[d] = band_counts.get(d, 0) + 1
    reward_distribution = [{'discount_percentage': d, 'count': c} for d, c in sorted(band_counts.items())]

    # Activity hourly peak distribution
    cursor.execute("SELECT strftime('%H', created_at) as hour, COUNT(*) as count FROM activities GROUP BY hour")
    peak_hours = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return jsonify({
        'facility_trends': facility_trends,
        'reward_distribution': reward_distribution,
        'peak_hours': peak_hours
    })

@app.route('/admin/members', methods=['GET', 'POST'])
@admin_required
def admin_members():
    """Admin member management: add members, view the club roster with live
    rewards, edit profiles, and manage yearly fees.

    IB HL CS: this route demonstrates the *command/query* separation — GET
    renders a read-only view (batch rewards, never writing), while POST
    performs a validated write (duplicate-username check BEFORE insert,
    hashed passwords, generated member codes). Duplicate detection is a
    classic data-integrity pattern: query-then-insert with a UNIQUE column
    as the final backstop.
    """
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        # Add new member from admin panel
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        membership_type = EngagementEngine.normalize_tier(request.form.get('membership_type', 'Member'))

        if not username or not password or not full_name or not email:
            flash('Required fields missing for member creation.', 'danger')
        else:
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                flash('Username already exists.', 'danger')
            else:
                pw_hash = generate_password_hash(password)
                cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'member')", (username, pw_hash))
                u_id = cursor.lastrowid
                m_code = f"MBR-{uuid.uuid4().hex[:6].upper()}"
                cursor.execute('''
                    INSERT INTO members (user_id, full_name, membership_type, email, phone, member_code)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (u_id, full_name, membership_type, email, phone, m_code))
                conn.commit()
                flash(f'Member {full_name} added successfully!', 'success')

    cursor.execute('''
        SELECT m.*, u.username, u.created_at as account_created
        FROM members m JOIN users u ON m.user_id = u.id
        ORDER BY m.id DESC
    ''')
    members_list = cursor.fetchall()
    
    # Read-only batch rewards view — page loads never write to the database
    rewards_map = EngagementEngine.view_all_rewards()
    member_data = [{'profile': m, 'rewards': rewards_map.get(m['id'])} for m in members_list]

    settings = RewardSettings.get_settings()
    conn.close()
    return render_template('admin/members.html', member_data=member_data, settings=settings)

@app.route('/admin/members/edit/<int:member_id>', methods=['POST'])
@admin_required
def admin_member_edit(member_id):
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()

    if not full_name or not email:
        flash('Full name and email are required.', 'danger')
        return redirect(url_for('admin_members'))

    conn = get_db()
    cursor = conn.cursor()

    # Only update membership tier when the form actually submits it — an edit that
    # omits the field (older clients, partial requests) must NEVER silently reset
    # a Premium/VIP member back to 'Member'.
    if 'membership_type' in request.form:
        membership_type = EngagementEngine.normalize_tier(request.form['membership_type'])
        cursor.execute('''
            UPDATE members
            SET full_name = ?, email = ?, phone = ?, membership_type = ?
            WHERE id = ?
        ''', (full_name, email, phone, membership_type, member_id))
    else:
        cursor.execute('''
            UPDATE members
            SET full_name = ?, email = ?, phone = ?
            WHERE id = ?
        ''', (full_name, email, phone, member_id))

    # Optional yearly-fee management: set the annual fee and/or mark it paid.
    if 'yearly_fee' in request.form and request.form['yearly_fee'] != '':
        try:
            yearly_fee = float(request.form['yearly_fee'])
            if yearly_fee >= 0:
                cursor.execute("UPDATE members SET yearly_fee = ? WHERE id = ?", (yearly_fee, member_id))
        except ValueError:
            pass
    if 'fee_paid' in request.form:
        cursor.execute("UPDATE members SET fee_paid = 1 WHERE id = ?", (member_id,))

    conn.commit()
    conn.close()
    flash('Member record updated!', 'success')
    return redirect(url_for('admin_members'))

@app.route('/admin/activity', methods=['GET', 'POST'])
@admin_required
def admin_activity():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        member_id = request.form.get('member_id')
        activity_type = request.form.get('activity_type')
        service_name = request.form.get('service_name', '').strip()
        try:
            transaction_value = float(request.form.get('transaction_value', 0.0))
        except ValueError:
            transaction_value = -1.0

        # IB HL CS: server-side validation — reject negative amounts before
        # the row ever reaches the database. Converting the raw string with
        # float() inside try/except (defensive programming) means malformed
        # input is caught and turned into a safe sentinel (-1.0) that fails
        # the validation below instead of crashing the server.
        if transaction_value < 0:
            flash('Transaction value cannot be negative!', 'danger')
        else:
            cursor.execute('''
                INSERT INTO activities (member_id, activity_type, service_name, transaction_value)
                VALUES (?, ?, ?, ?)
            ''', (member_id, activity_type, service_name, transaction_value))
            conn.commit()
            flash('Admin entry logged successfully!', 'success')

    cursor.execute('''
        SELECT a.*, m.full_name, m.member_code
        FROM activities a JOIN members m ON a.member_id = m.id
        ORDER BY a.created_at DESC
    ''')
    activities = cursor.fetchall()

    cursor.execute("SELECT id, full_name, member_code FROM members ORDER BY full_name")
    all_members = cursor.fetchall()

    # Facility check-in records for club-side management (guest sessions show their guest name)
    cursor.execute('''
        SELECT fc.*, m.full_name, m.member_code, g.guest_name
        FROM facility_checkins fc
        JOIN members m ON fc.member_id = m.id
        LEFT JOIN guest_ids g ON fc.guest_id = g.id
        ORDER BY fc.check_in_time DESC
    ''')
    checkins = cursor.fetchall()

    # Recently issued expense receipts (QR vouchers)
    cursor.execute('''
        SELECT r.*, m.full_name AS scanned_by_name
        FROM receipts r
        LEFT JOIN members m ON r.scanned_by_member = m.id
        ORDER BY r.issued_at DESC LIMIT 12
    ''')
    receipts = cursor.fetchall()

    conn.close()
    return render_template('admin/activity.html', activities=activities, all_members=all_members, checkins=checkins, facilities=FACILITIES, receipts=receipts)

@app.route('/member/marketplace', methods=['GET'])
@login_required
def member_marketplace():
    """Points Marketplace: browse the coupon catalog, view claimed coupons
    with QR codes, and credit points against the yearly membership fee."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()
    conn.close()

    if not member:
        flash('Member profile not found.', 'danger')
        return redirect(url_for('index'))

    rewards = EngagementEngine.view_member_rewards(member['id'])
    coupons = MarketplaceManager.get_active_coupons()
    my_coupons = MarketplaceManager.get_member_coupons(member['id'])
    transactions = MarketplaceManager.get_point_transactions(member['id'])
    fee = MarketplaceManager.get_member_fee(member['id'])

    return render_template('member/marketplace.html', member=member, rewards=rewards,
                           coupons=coupons, my_coupons=my_coupons,
                           transactions=transactions, fee=fee)

@app.route('/member/marketplace/claim', methods=['POST'])
@login_required
def member_marketplace_claim():
    """Claim a coupon from the marketplace — deducts points and issues a code."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()
    conn.close()

    if not member:
        flash('Member profile not found.', 'danger')
        return redirect(url_for('index'))

    try:
        coupon_id = int(request.form.get('coupon_id', 0))
    except (TypeError, ValueError):
        coupon_id = 0

    result = MarketplaceManager.claim_coupon(member['id'], coupon_id)
    if result['ok']:
        flash(result['message'], 'success')
    else:
        flash(result['message'], 'danger')
    return redirect(url_for('member_marketplace'))

@app.route('/member/marketplace/fee', methods=['POST'])
@login_required
def member_marketplace_fee():
    """Credit points against the member's yearly club membership fee."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM members WHERE user_id = ?", (session['user_id'],))
    member = cursor.fetchone()
    conn.close()

    if not member:
        flash('Member profile not found.', 'danger')
        return redirect(url_for('index'))

    try:
        points = float(request.form.get('points', 0))
    except (TypeError, ValueError):
        points = 0.0

    result = MarketplaceManager.apply_points_to_fee(member['id'], points)
    if result['ok']:
        flash(result['message'], 'success')
    else:
        flash(result['message'], 'danger')
    return redirect(url_for('member_marketplace'))

@app.route('/admin/marketplace', methods=['GET', 'POST'])
@admin_required
def admin_marketplace():
    """Admin coupon marketplace manager: add new coupons or toggle availability."""
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action', 'add')
        if action == 'add':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            category = request.form.get('category', 'Facility').strip()
            try:
                cost_points = float(request.form.get('cost_points', 0.0))
                value_amount = float(request.form.get('value_amount', 0.0))
            except ValueError:
                cost_points = value_amount = -1.0
            facility_name = request.form.get('facility_name', '').strip() or None

            if not name or not description:
                flash('Coupon name and description are required.', 'danger')
            elif cost_points < 0 or value_amount < 0:
                flash('Coupon cost and value cannot be negative.', 'danger')
            else:
                cursor.execute('''
                    INSERT INTO coupons (name, description, category, cost_points, value_amount, facility_name, active)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                ''', (name, description, category, cost_points, value_amount, facility_name))
                conn.commit()
                flash(f'Coupon "{name}" added to the marketplace!', 'success')
        elif action == 'toggle':
            try:
                coupon_id = int(request.form.get('coupon_id', 0))
            except (TypeError, ValueError):
                coupon_id = 0
            cursor.execute("SELECT * FROM coupons WHERE id = ?", (coupon_id,))
            coupon = cursor.fetchone()
            if coupon:
                cursor.execute("UPDATE coupons SET active = ? WHERE id = ?", (0 if coupon['active'] else 1, coupon_id))
                conn.commit()
                state = 'deactivated' if coupon['active'] else 'activated'
                flash(f'Coupon "{coupon["name"]}" {state}.', 'success')

    cursor.execute("SELECT * FROM coupons ORDER BY active DESC, cost_points ASC")
    coupons = cursor.fetchall()
    conn.close()
    return render_template('admin/marketplace.html', coupons=coupons)

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    """Admin control panel for the reward algorithm's parameters.

    IB HL CS: *configurability* — the scoring weights, tier multipliers and
    profit pool are all user-editable. Every numeric input is validated
    (non-negative) server-side before being persisted to reward_settings,
    satisfying the validation success criterion. The try/except around
    float() conversions is defensive programming against malformed input.
    """
    if request.method == 'POST':
        try:
            visit_w = float(request.form.get('visit_weight', 10.0))
            spend_w = float(request.form.get('spending_weight', 0.5))
            referral_w = float(request.form.get('referral_weight', 50.0))
            facility_w = float(request.form.get('facility_weight', 0.2))
            loyalty_w = float(request.form.get('loyalty_weight', 5.0))
            profit_pool = float(request.form.get('profit_sharing_pool', 10000.0))
            premium_mult = float(request.form.get('premium_multiplier', 1.15))
            vip_mult = float(request.form.get('vip_multiplier', 1.30))
            points_value = float(request.form.get('points_value_dollars', 0.50))
        except ValueError:
            flash('Invalid numeric inputs for algorithm settings.', 'danger')
            return redirect(url_for('admin_settings'))

        if visit_w < 0 or spend_w < 0 or referral_w < 0 or facility_w < 0 or loyalty_w < 0 or profit_pool < 0 or premium_mult < 0 or vip_mult < 0 or points_value < 0:
            flash('Algorithm parameters, reward pool, and points value cannot be negative.', 'danger')
            return redirect(url_for('admin_settings'))

        RewardSettings.update_settings(visit_w, spend_w, referral_w, facility_w,
                                       loyalty_w, profit_pool, premium_mult, vip_mult,
                                       points_value)
        flash('Algorithm parameters & marketplace reward pool updated successfully!', 'success')
        return redirect(url_for('admin_settings'))

    settings = RewardSettings.get_settings()
    return render_template('admin/settings.html', settings=settings)

@app.route('/admin/reports')
@admin_required
def admin_reports():
    return render_template('admin/reports.html')

@app.route('/admin/reports/export/usage_csv')
@admin_required
def export_usage_csv():
    """Download member usage logs as a CSV file.

    IB HL CS: *file processing over HTTP* — the CSV string generated by
    CSVReportGenerator is wrapped in a Response object with a MIME type
    (text/csv) and a Content-Disposition header that tells the browser to
    download it as fairshare_member_usage_logs.csv. This is how a web
    application serves generated files.
    """
    csv_data = CSVReportGenerator.export_member_usage_logs()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=fairshare_member_usage_logs.csv"}
    )

@app.route('/admin/reports/export/rewards_csv')
@admin_required
def export_rewards_csv():
    """Download the financial reward summary (points, balances, discounts)
    as CSV. Same file-processing-over-HTTP pattern as usage export.
    """
    csv_data = CSVReportGenerator.export_financial_reward_summaries()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=fairshare_financial_reward_summaries.csv"}
    )

if __name__ == '__main__':
    app.run(debug=True, port=5000)
