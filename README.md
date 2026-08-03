# FairShare

A web application for recreational organisations that rewards members based on their engagement and value generated for the organisation.

## Project Overview

FairShare is designed for country clubs and similar recreational organisations to move away from flat subscription models toward a value-based reward system. The system tracks member visits, guest referrals, facility usage, restaurant spending, and shop purchases to calculate an engagement score that is automatically converted into personalised rewards such as discounts, cashback, or redemption codes.

### Core Problem

Traditional clubs charge members a flat fee regardless of their contribution level. Highly active members who visit often, invite guests, and spend money at internal facilities receive no additional recognition, which can reduce loyalty. FairShare solves this by creating a transparent reward cycle that recognises and rewards high-value members.

## Technology Stack

- **Backend**: Python with Flask
- **Frontend**: HTML, CSS, JavaScript
- **Database**: SQLite
- **Templates**: Jinja HTML templates
- **Authentication**: Flask sessions with hashed passwords
- **Charts**: Chart.js
- **Export**: Python CSV module

## Features

### Member Features

- Secure login with encrypted passwords
- View engagement score and total value generated
- View current rewards and discounts
- See recent visits, purchases, referrals, and facility usage
- Generate barcode/QR code for check-ins
- Generate redemption codes for discounts
- Register guest visits

### Administrator Features

- Secure admin login
- View and manage all member records
- Record visits, spending, referrals, and facility usage
- Adjust reward algorithm weightings
- Set reward/profit-sharing pool amounts
- View engagement trends with charts
- Export usage and reward summaries as CSV files

## Success Criteria

1. Secure login for members and administrators with encrypted passwords
2. Relational database storage without data duplication
3. Recording of member visits, facility usage, and purchases with timestamps
4. Automatic engagement score calculation based on configurable factors
5. Automatic personalised discount generation based on engagement score
6. Member dashboard displaying reward status, engagement score, and discounts
7. Unique user ID barcode for facility check-in/check-out
8. Facility usage tracking with duration calculation
9. Guest ID creation for tracking guest visits and spending
10. Admin control panel for algorithm settings and member management
11. Redemption QR code/coupon code generation for discounts
12. Responsive UI for mobile, tablet, and desktop
13. Fast page loading (under 2-3 seconds) with asset caching
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

## Project Structure

```
Code/
├── main.py              # Flask application entry point
├── database.py          # Database connection and operations
├── models.py            # Data models
├── config.py            # Configuration settings
├── requirements.txt     # Python dependencies
├── data/
│   └── fairshare.db     # SQLite database
├── static/
│   ├── css/
│   │   └── styles.css   # Stylesheets
│   ├── js/
│   │   └── app.js       # JavaScript functionality
│   └── images/
├── templates/
│   ├── base.html        # Base template
│   ├── index.html       # Landing page
│   ├── auth/
│   │   ├── login.html   # Login page
│   │   └── register.html # Registration page
│   ├── member/
│   │   ├── dashboard.html
│   │   ├── activity.html
│   │   └── rewards.html
│   └── admin/
│       ├── dashboard.html
│       ├── members.html
│       ├── activity.html
│       ├── settings.html
│       └── reports.html
└── tests/
    ├── test_app.py
    └── test_rewards.py
```

## Database Schema

### users
- id, username, password_hash, role, created_at

### members
- id, user_id, full_name, membership_type, email, phone, join_date

### activities
- id, member_id, activity_type, service_name, transaction_value, guest_count, check_in_time, check_out_time, created_at

### reward_settings
- id, visit_weight, spending_weight, referral_weight, reward_pool, updated_at

### rewards
- id, member_id, engagement_score, discount_percentage, reward_value, redemption_code, status, created_at

## Reward Algorithm

The engagement score is calculated using configurable weightings:

```
engagement_score = (visits × visit_weight) + (total_spending × spending_weight) + (guest_referrals × referral_weight)
```

Reward bands:
- 0-49 points: no reward
- 50-99 points: 5% discount
- 100-199 points: 10% discount
- 200+ points: 15% discount

## Computer Science Concepts

This project demonstrates key IB Computer Science concepts:

- **Databases**: Relational design with SQL queries and joins
- **Computational Thinking**: Decomposition, abstraction, pattern recognition, algorithm design
- **Algorithms**: Engagement score calculation and reward band assignment
- **Networks**: Client-server model with HTTP requests
- **Security**: Password hashing, session management, role-based access control
- **Validation**: Client- and server-side input validation
- **File Processing**: CSV export functionality

## License

This project is part of an IB Computer Science Internal Assessment.

## Author

Yashvir Mishra - CS IA 2027
