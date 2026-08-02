# FairShare Computer Science Concepts Mapping

This document maps the major IB Computer Science concepts from the Hodder 2025 textbook to the FairShare IA project. The goal is not to force every concept into the product, but to use the concepts that naturally support the problem and can be clearly explained in the IA documentation.

## Best Overall Direction

FairShare should be built as a database-driven web application. The strongest CS concepts for this project are:

- Databases
- Computational thinking
- Algorithms
- Programming constructs
- Data structures
- File processing
- Object-oriented programming
- Networks and security
- Validation and testing

These concepts directly support the system's main purpose: recording member activity, calculating engagement, generating rewards, and giving different users controlled access to the system.

## A1 Computer Fundamentals

This topic is not the main focus of the product, but it can be referenced briefly in the system overview.

### How It Applies

- The application runs on a client-server model.
- The user's browser sends requests to the Flask server.
- The server processes data and sends HTML pages back to the browser.
- The database stores records on secondary storage.
- RAM is used while the application runs and processes user requests.

### IA Evidence

Use this in Criterion C when explaining the system architecture. A simple diagram can show:

```text
Browser -> Flask server -> SQLite database -> Flask server -> Browser
```

## A2 Networks

This concept fits strongly because FairShare is a web application.

### How It Applies

- Members and administrators access the system through a web browser.
- HTTP requests are used when pages are loaded or forms are submitted.
- Role-based access protects admin pages from ordinary members.
- In a real deployment, HTTPS would protect data transmitted between the browser and server.

### IA Evidence

Explain that the prototype runs locally, but the design follows a networked web application structure. Mention that sensitive data such as passwords and member activity should be protected during transmission and storage.

## A2 Network Security

This is useful for login and admin protection.

### How It Applies

- Passwords should be stored as hashes, not plain text.
- Sessions should identify logged-in users.
- Admin-only routes should check the user's role before displaying pages.
- Input validation should reduce invalid or malicious entries.

### IA Evidence

Use screenshots and code snippets showing:

- Password hashing
- Login session creation
- Admin route protection
- Validation for invalid transaction values

## A3 Databases

This should be one of the strongest parts of the IA.

### How It Applies

FairShare needs a relational database because it stores linked data:

- Users have login accounts.
- Members are linked to users.
- Activities are linked to members.
- Rewards are generated from activities.
- Settings control the reward algorithm.

### Recommended Tables

```text
users(id, username, password_hash, role, created_at)
members(id, user_id, full_name, membership_type, email, phone, join_date)
activities(id, member_id, activity_type, service_name, transaction_value, guest_count, check_in_time, check_out_time, created_at)
reward_settings(id, visit_weight, spending_weight, referral_weight, reward_pool, updated_at)
rewards(id, member_id, engagement_score, discount_percentage, reward_value, redemption_code, status, created_at)
```

### IA Evidence

Include:

- Entity relationship diagram
- Table descriptions
- Primary keys and foreign keys
- Example SQL queries
- Explanation of how duplication is reduced

## A3 Database Design

This concept is especially relevant to Criterion B planning.

### How It Applies

The database should avoid duplicated data by separating users, members, activities, settings, and rewards into different tables.

Example:

- Do not store the member's name inside every activity record.
- Store `member_id` in `activities`, then use a join to access member details.

### IA Evidence

Show one example of a join query:

```sql
SELECT members.full_name, activities.activity_type, activities.transaction_value
FROM activities
JOIN members ON activities.member_id = members.id;
```

## A3 Database Programming

This supports the actual implementation.

### How It Applies

The Python code should perform CRUD operations:

- Create new users, members, activities, and rewards.
- Read dashboard data.
- Update member details and reward settings.
- Delete or deactivate incorrect records if needed.

### IA Evidence

Show selected code for:

- Connecting to SQLite
- Inserting an activity
- Querying a member's activity history
- Calculating reward totals from database records

## A4 Machine Learning

Machine learning is optional and should not be part of the MVP.

### How It Could Apply

If there is enough time, a simple recommendation system could suggest offers based on member behaviour.

Example:

- Members who spend often at the restaurant receive dining discounts.
- Members who frequently book courts receive facility booking offers.
- Members who refer guests receive referral rewards.

### Recommendation

Do not build full machine learning for the IA. A rules-based recommendation system is more realistic and easier to explain. You can mention machine learning as a future improvement in Criterion E.

## B1 Computational Thinking

This should appear throughout the IA.

### Decomposition

Break the system into smaller parts:

- Login system
- Member dashboard
- Admin dashboard
- Activity recording
- Reward calculation
- Reports and exports

### Abstraction

Represent real-world club behaviour using simplified data:

- A visit becomes an activity record.
- A purchase becomes a transaction value.
- A referral becomes a guest count.
- Loyalty becomes an engagement score.

### Pattern Recognition

Identify common activity types:

- Visit
- Purchase
- Referral
- Facility booking

### Algorithm Design

Create a repeatable process for calculating rewards from activity data.

## B2 Programming Fundamentals

This will be shown directly in the code.

### How It Applies

- Variables store user input and calculated totals.
- Selection is used for login checks and reward bands.
- Loops are used to process activity records.
- Functions are used to separate logic into reusable parts.
- Modules separate the application into files.

### IA Evidence

Use code snippets showing:

- `if` statements for role checking
- `for` loops for activity totals
- Functions such as `calculate_engagement_score()`
- Form handling routes

## B2 Programming Constructs

This is important for validation and control flow.

### How It Applies

Examples:

- If a user is not logged in, redirect to login.
- If the logged-in user is not an admin, block admin pages.
- If transaction value is negative, reject the form.
- If engagement score crosses a threshold, assign a higher discount.

### IA Evidence

Include examples of:

- Sequence
- Selection
- Iteration
- Validation logic

## B2 Data Structures

This concept can be shown through Python and database structures.

### How It Applies

- Lists can store activity rows from the database.
- Dictionaries can pass dashboard data to templates.
- Tuples are returned by SQLite queries.
- Tables store persistent structured data.

### IA Evidence

Explain why database tables are the main data structure and how Python dictionaries/lists are used to prepare page data.

## B2 Algorithms

This should be one of the clearest parts of Criterion D.

### Main Algorithm

The core algorithm calculates engagement and rewards.

```text
Get all activities for a member
Calculate total visits
Calculate total spending
Calculate guest referrals
Apply weighting values
Generate engagement score
Assign discount band
Store or display reward
```

### Example Formula

```text
engagement_score =
  (visits * visit_weight)
  + (total_spending * spending_weight)
  + (guest_referrals * referral_weight)
```

### IA Evidence

Use pseudocode, flowcharts, and code snippets. Test the algorithm with low, medium, and high engagement examples.

## B2 File Processing

This fits the CSV export feature.

### How It Applies

Administrators can export usage logs or reward summaries as CSV files.

### IA Evidence

If implemented, show code that writes database query results into a CSV file. This is a good extension because it demonstrates practical file handling.

## B3 Object-Oriented Programming

OOP is useful but should be used carefully.

### How It Applies

You can create classes for:

- `User`
- `Member`
- `Activity`
- `Reward`

However, if the Flask and SQLite code becomes simpler without full OOP, you can still use functions and database tables. The IA rewards appropriate complexity, not artificial complexity.

### Recommended Approach

Use light OOP for the reward logic only if it makes the code clearer.

Example:

```text
RewardCalculator
- stores weighting settings
- calculates engagement score
- calculates discount percentage
```

## B4 Abstract Data Types

This is optional for the project.

### How It Could Apply

- A queue could model check-in events waiting to be processed.
- A stack could model undo history for admin edits.
- A list could store a member's recent activities.

### Recommendation

Do not force ADTs into the MVP unless there is a natural reason. A simple list of recent activities is enough to discuss basic data structures.

## Ethics and Social Impact

This is important because the system handles personal and financial behaviour data.

### Issues To Discuss

- Privacy of member spending and visit data
- Fairness of reward calculation
- Transparency of how discounts are generated
- Security of login information
- Risk of over-rewarding wealthy members who spend more
- Need for admin oversight and configurable weightings

### IA Evidence

Discuss these in Criterion A and Criterion E. Explain how the system tries to be fair by using clear weighting rules rather than hidden or arbitrary rewards.

## Best Concepts To Emphasise In The IA

These are the most valuable concepts for scoring well:

1. Relational database design
2. SQL queries and joins
3. Authentication and role-based access
4. Validation
5. Engagement score algorithm
6. Reward band algorithm
7. Member/admin dashboards
8. CSV export
9. Testing with expected and actual results
10. Evaluation against success criteria

## Concepts To Mention But Not Overbuild

These concepts can be mentioned, but they should not dominate the project:

- Computer hardware
- Operating systems
- Low-level data representation
- Full machine learning
- Advanced ADTs
- GPU/CPU processing

They are part of the textbook, but they do not naturally form the core of this IA product.

## Final Build Strategy

The best way to use the textbook concepts is to build FairShare in layers:

1. Build the database.
2. Add login and role protection.
3. Add member and admin dashboards.
4. Add activity recording.
5. Add reward calculation.
6. Add validation.
7. Add CSV export or charts.
8. Document the algorithms and database design clearly.

This gives the project enough technical depth without becoming too large or difficult to finish.
