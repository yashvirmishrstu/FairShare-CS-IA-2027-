# FairShare Project Overview

## Project Aim

FairShare is a web application for recreational organisations such as country clubs. Its purpose is to reward members based on the value they generate for the organisation through visits, guest referrals, facility use, restaurant spending, shop purchases, and other engagement activities.

Instead of giving every member the same treatment under a fixed subscription model, the system calculates each member's engagement and automatically converts it into personalised rewards such as discounts, cashback, or redemption codes.

## Core Problem

Traditional clubs charge members a flat fee, even though different members contribute very different levels of value. Highly active members may visit often, invite guests, and spend money at internal facilities, but they receive no additional recognition. This can reduce loyalty because the most valuable members are treated the same as inactive members.

FairShare solves this by creating a transparent reward cycle:

1. The member uses club services.
2. The system records visits, referrals, spending, and facility usage.
3. The system calculates an engagement score.
4. The system converts the score into discounts or rewards.
5. The member can view and redeem their reward.
6. Administrators can monitor engagement and adjust reward settings.

## Recommended Technology Stack

For a CS IA project, the best approach is to keep the technology simple, explainable, and easy to document.

- Backend: Python with Flask
- Frontend: HTML, CSS, and basic JavaScript
- Database: SQLite
- Templates: Jinja HTML templates
- Charts: Chart.js or simple generated summaries
- Export: Python CSV module
- Authentication: Flask sessions with hashed passwords

This stack is suitable because it supports both the member-facing and admin-facing web pages without adding unnecessary complexity.

## Main User Roles

### Member

Members should be able to:

- Log in securely.
- View their engagement score.
- View their current reward or discount.
- See recent visits, purchases, referrals, and facility usage.
- Scan a barcode or QR code for check-ins.
- Generate a redemption code for available discounts.
- Add or register a guest visit if required.

### Administrator

Administrators should be able to:

- Log in securely.
- View all member records.
- Add, edit, or remove member details.
- Record visits, spending, referrals, and facility usage.
- Adjust reward algorithm weightings.
- Set the available reward or profit-sharing pool.
- View charts showing engagement trends.
- Export usage and reward summaries as CSV files.

## Minimum Viable Product

The IA should focus first on a realistic core version. The MVP should include only the features needed to prove the computational solution works.

### MVP Features

1. Secure login for members and administrators.
2. SQLite database storing users, members, activity records, rewards, and settings.
3. Member dashboard showing engagement score, total value generated, and current discount.
4. Admin dashboard showing members, activity totals, and reward levels.
5. Activity recording for visits, purchases, and guest referrals.
6. Reward algorithm that calculates discounts automatically.
7. Validation to prevent invalid entries, duplicate usernames, and unauthorised admin access.

These features are enough to demonstrate the main computational thinking: data storage, data processing, automated calculation, role-based access, validation, and useful output.

## Optional Extension Features

These features are good, but they should only be added after the MVP works.

- QR code or barcode scanning for member check-ins.
- Guest ID creation and guest spending tracking.
- Facility check-in and check-out timestamps.
- Usage duration calculation.
- Admin charts for peak hours and reward distribution.
- CSV export for member usage logs.
- Mobile responsiveness refinements.
- Cached static assets for faster loading.

## Suggested File Structure

```text
Code/
|-- main.py
|-- database.py
|-- models.py
|-- config.py
|-- requirements.txt
|-- README.md
|-- PROJECT_OVERVIEW.md
|-- data/
|   `-- fairshare.db
|-- static/
|   |-- css/
|   |   `-- styles.css
|   |-- js/
|   |   `-- app.js
|   `-- images/
|-- templates/
|   |-- base.html
|   |-- index.html
|   |-- auth/
|   |   |-- login.html
|   |   `-- register.html
|   |-- member/
|   |   |-- dashboard.html
|   |   |-- activity.html
|   |   `-- rewards.html
|   `-- admin/
|       |-- dashboard.html
|       |-- members.html
|       |-- activity.html
|       |-- settings.html
|       `-- reports.html
`-- tests/
    `-- test_rewards.py
```

## Suggested Database Tables

### users

Stores login information.

- id
- username
- password_hash
- role
- created_at

### members

Stores member profile information.

- id
- user_id
- full_name
- membership_type
- email
- phone
- join_date

### activities

Stores member engagement records.

- id
- member_id
- activity_type
- service_name
- transaction_value
- guest_count
- check_in_time
- check_out_time
- created_at

### reward_settings

Stores configurable algorithm settings.

- id
- visit_weight
- spending_weight
- referral_weight
- reward_pool
- updated_at

### rewards

Stores generated reward results.

- id
- member_id
- engagement_score
- discount_percentage
- reward_value
- redemption_code
- status
- created_at

## Reward Algorithm Plan

The reward algorithm should be simple enough to explain in the IA, but detailed enough to show computational skill.

Example formula:

```text
engagement_score =
  (number_of_visits * visit_weight)
  + (total_spending * spending_weight)
  + (guest_referrals * referral_weight)
```

Example reward bands:

```text
0-49 points: no reward
50-99 points: 5% discount
100-199 points: 10% discount
200+ points: 15% discount
```

This is useful for the IA because it can be tested with different inputs and justified using stakeholder needs.

## Development Roadmap

### Phase 1: Foundation

- Finalise success criteria.
- Build the Flask project structure.
- Create the SQLite database.
- Create the basic member and admin pages.
- Add sample data for testing.

### Phase 2: Authentication

- Create login page.
- Store hashed passwords.
- Add session-based login.
- Redirect members and admins to different dashboards.
- Protect admin-only pages.

### Phase 3: Activity Tracking

- Create forms for recording visits, purchases, and referrals.
- Save activity records to the database.
- Display activity history on the member dashboard.
- Add validation for negative values and missing fields.

### Phase 4: Reward Calculation

- Create the engagement score function.
- Calculate discounts automatically.
- Store generated rewards.
- Show reward status on the member dashboard.
- Allow admin users to edit algorithm settings.

### Phase 5: Admin Reporting

- Create admin tables showing member activity.
- Add summary statistics.
- Add simple charts or visual summaries.
- Add CSV export if time allows.

### Phase 6: Testing and IA Evidence

- Test login and role protection.
- Test invalid inputs.
- Test reward calculations with low, medium, and high engagement members.
- Take screenshots of each major page.
- Explain how the system meets each success criterion.

## IA Documentation Strategy

For the IA write-up, the project should be documented around clear evidence.

- Criterion A: Explain the club reward problem and identify stakeholders.
- Criterion B: Show planning diagrams, database design, success criteria, and UI sketches.
- Criterion C: Explain the main algorithms, database operations, validation, and page routing.
- Criterion D: Show testing tables with expected and actual results.
- Criterion E: Evaluate whether each success criterion was met and discuss improvements.

## Recommended Scope Control

The project should not try to build every possible feature at once. The safest IA approach is:

1. Build login, database, member dashboard, admin dashboard, activity tracking, and reward calculation first.
2. Add QR codes, charts, exports, and guest tracking only after the core system works.
3. Keep the reward algorithm transparent so it can be explained and tested clearly.

## Immediate Next Steps

1. Replace the current sample data system with SQLite.
2. Create database setup code.
3. Add real login pages.
4. Add a member dashboard linked to database records.
5. Add an admin page for entering activity records.
6. Implement the engagement score and discount calculation.
