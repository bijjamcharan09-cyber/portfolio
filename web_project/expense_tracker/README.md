# Expense Tracker (Multi-User RBAC Platform + Guest Mode + Excel)

A modern, secure multi-user personal finance platform built with Flask, SQLite / Turso (hosted libSQL), vanilla HTML/CSS/JavaScript, and pytest. It features session-based authentication, role-based access control (Admin & User roles), strict user-level data isolation (IDOR-prevented), category filtering, monthly/annual summaries, interactive Matplotlib charts, live currency conversions, Excel (.xlsx) Import/Export with formula injection defenses, and an isolated One-Time Guest Mode Trial for new visitors.

---

## Architecture Overview

| Environment | Database Layer | Storage Mode | Driver |
|---|---|---|---|
| **Local Development** | SQLite 3 | Local file (`data/tracker.db`) | Standard library `sqlite3` |
| **Automated Testing** | SQLite 3 | Isolated temporary file (`tmp_path / test.db`) | Standard library `sqlite3` |
| **Production (Vercel)** | Turso Cloud | Hosted SQLite-compatible libSQL | `turso_serverless` (pure Python PEP 249) / `libsql` |

### Core Security & Architectural Principles:
- **Authentication**: Secure session-based authentication with Werkzeug password hashing (`scrypt`/`pbkdf2`). Plaintext passwords are never stored.
- **Session Security**: HTTP-only cookies (`SESSION_COOKIE_HTTPONLY=True`), SameSite=Lax, Secure cookies in production (`SESSION_COOKIE_SECURE=True`), and session fixation prevention (`session.clear()` on login/logout).
- **Role-Based Access Control (RBAC)**: Centralized server-side `@login_required`, `@admin_required`, and `@guest_required` decorators.
  - **Admin**: Views system metrics, manages users (activate/deactivate), deletes accounts with safeguards (cannot delete self, cannot delete sole admin), cannot access private user expenses.
  - **User**: Manages personal expenses (add, edit, delete), views personal analytics and reports, imports/exports personal records via Excel. Cannot access or manipulate another user's records (IDOR protection).
  - **Guest**: Explores a full-featured demo dashboard with realistic preloaded sample transactions, monthly summaries, charts, and Excel import/export. Guests can never access admin dashboards, registered-user records, or private account settings.
- **One-Time Guest Trial Enforcement**: Enforced via a tamper-proof, signed server cookie (`guest_trial_record`). The session automatically expires after 30 minutes of inactivity and purges temporary demo records.
  - *Limitation Note*: In accordance with web privacy standards and non-invasive guidelines, invasive device fingerprinting is not used. Clearing browser cookies/storage or using an alternate browser/device allows initiating a new trial.
- **Data Isolation**: Registered transactions are stored in `transactions` (scoped to `user_id`). Guest trial data is stored in a separate table `guest_transactions` (scoped to `guest_id` with `expires_at`). Guest queries physically cannot access or contaminate registered records.
- **Excel Import/Export Security**: Uses `openpyxl`. Validates `.xlsx` format, file size limits (4 MB), column headers, and data types. Formula injection protection strips leading formula symbols (`=`, `+`, `-`, `@`) upon import and sanitizes exported cells with single-quote escaping.
- **Money Storage**: Stored strictly as integer cents (e.g. `12.50` stored as `1250`) to eliminate floating-point rounding errors.
- **SQL Security**: 100% parameterized queries using `?` placeholders across both local SQLite and remote Turso drivers.
- **Credential Safety**: Authentication tokens are never printed in logs or exposed in HTTP responses.

---

## Prerequisites & Supported Python Versions

- **Python**: Python 3.9, 3.10, 3.11, 3.12, 3.13, or 3.14 (supports Windows x86_64, Windows ARM64, macOS, and Linux).
- **Turso CLI** (optional, for managing Turso databases): [Install Turso CLI](https://docs.turso.tech/cli/introduction).
- **Vercel CLI** (optional, for CLI deployments): `npm i -g vercel`.

---

## Local Installation

### 1. Enter the project directory
```powershell
# Windows PowerShell
cd C:\Users\bijja\Portfolio-Showcase\web_project\expense_tracker
```

### 2. Create and activate a virtual environment
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
*(On macOS/Linux: `source venv/bin/activate`)*

### 3. Install dependencies
```powershell
pip install -r requirements.txt
```

---

## Local Development with SQLite

1. Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```

2. Generate a secure secret key:
   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Paste the generated string into `SECRET_KEY` in your `.env` file.

3. Keep `DATABASE_MODE=sqlite` in `.env`:
   ```dotenv
   FLASK_ENV=development
   SECRET_KEY=your-generated-secret-key
   DATABASE_MODE=sqlite
   SQLITE_DATABASE_PATH=data/tracker.db
   BASE_CURRENCY=INR(₹)
   ```

4. Initialize database schema:
   ```powershell
   flask --app run.py init-db
   ```

5. (Optional) Create an initial administrator account via CLI:
   ```powershell
   flask --app run.py create-admin
   ```
   *(Note: The very first user to register via `/register` also automatically receives the `admin` role!)*

6. Start the development server:
   ```powershell
   python run.py
   ```
   Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

## Production Setup with Turso

[Turso](https://turso.tech) is an edge-hosted, SQLite-compatible database built on libSQL. It provides persistent storage for serverless environments where local file storage is ephemeral.

### 1. Create a Turso Database
```bash
turso auth login
turso db create expense-tracker-db
```

### 2. Obtain Database URL and Authentication Token
```bash
# Show database URL (e.g., libsql://expense-tracker-db-<org>.turso.io)
turso db show expense-tracker-db --url

# Create an authentication token
turso db tokens create expense-tracker-db
```

### 3. Remote Schema Initialization on Turso
Initialize the tables (`users`, `transactions`) and indexes idempotently on Turso:
```powershell
python scripts/init_turso_db.py --url "libsql://expense-tracker-db-<org>.turso.io" --token "your-token"
```

---

## Deployment to Vercel

Vercel provides serverless execution for Python applications. Because Vercel serverless functions have an ephemeral, read-only filesystem, Turso serves as the persistent cloud database and Flask client-side signed cookies serve as persistent sessions.

### 1. Configure Environment Variables in Vercel

In your Vercel Project Dashboard (**Settings > Environment Variables**), set:

| Variable | Value | Description |
|---|---|---|
| `FLASK_ENV` | `production` | Enables production mode and strict security checks |
| `SECRET_KEY` | *(random 32+ char secret)* | Production session/cookie signing key |
| `DATABASE_MODE` | `turso` | Enforces Turso cloud database connection |
| `TURSO_DATABASE_URL` | `libsql://<db>-<org>.turso.io` | Your Turso database endpoint |
| `TURSO_AUTH_TOKEN` | *(your auth token)* | Your Turso database token |
| `BASE_CURRENCY` | `INR(₹)` *(or USD, EUR)* | Default display currency |
| `ADMIN_EMAIL` | *(optional)* | Email automatically granted admin privileges |
| `FLASK_DEBUG` | `0` | Disables debug mode in production |

### 2. Vercel Project Root Directory Setting

If you imported the parent repository (`Portfolio-Showcase`) into Vercel, configure the Root Directory:
- Go to **Project Settings > General > Root Directory**.
- Set it to: `web_project/expense_tracker`.
- Save changes.

### 3. Deploy
```powershell
git push origin master
```

---

## Running the Automated Test Suite

The test suite runs against an isolated, temporary SQLite database (`tmp_path / test.db`) to ensure tests remain fast, self-contained, and completely independent of external network access or production credentials.

```powershell
python -m pytest -v
```

### Test Coverage (52 Passing Tests):
- **Authentication & Registration**: Registration with email validation, duplicate prevention, password hashing, login with active status check, logout.
- **RBAC & Authorization**: Admin routes protected against regular users, admin dashboard actions.
- **Data Isolation & IDOR**: Users cannot view, edit, or delete another user's transactions; personal reports aggregate only the owner's transactions.
- **Guest Mode Trial**: One-time trial enforcement, temporary session generation, sample data seeding, 30-minute inactivity timeout, guest blocked from admin routes and registered-user records.
- **Excel Import/Export**: .xlsx template generation, registered user export, guest export, safe Excel parsing with column validation, error tracking, duplicate deduplication, and formula injection defense.
- **Expense CRUD & Features**: Add, edit (PUT), delete transactions, monthly summaries, Matplotlib charts, currency conversion.
- **Production Validation**: Rejects insecure secret keys, requires Turso credentials in production.
- **Token Redaction**: Ensures database tokens are never exposed in exceptions or logs.

---

## Project Structure

```text
expense_tracker/
├── .env.example                  # Environment template (includes ADMIN_EMAIL)
├── .gitignore                     # Git ignore rules (.env, *.db ignored)
├── pytest.ini                     # Pytest configuration
├── README.md                      # Documentation
├── requirements.txt               # Dependencies (Flask, openpyxl, turso_serverless, etc.)
├── run.py                         # Local development server entry point
├── vercel.json                    # Vercel deployment rewrites
├── api/
│   └── index.py                   # Vercel Serverless Function entry point
├── app/
│   ├── __init__.py                # App factory, CLI commands, security headers
│   ├── api.py                     # REST endpoints (auth, admin, user, guest & Excel APIs)
│   ├── auth.py                    # RBAC decorators (@login_required, @admin_required, @guest_required, CSRF)
│   ├── config.py                  # Centralized configuration & environment parsing (4MB body limit)
│   ├── db.py                      # Database abstraction (SQLite & Turso, users, txs, guest_txs)
│   ├── validators.py              # Input validation (registration, login, profile, tx)
│   ├── views.py                   # Web routes (login, register, guest trial, logout, profile, admin)
│   ├── services/
│   │   ├── excel.py               # Excel .xlsx export, template generator & formula-safe parser
│   │   ├── exchange.py            # Frankfurter currency exchange service
│   │   └── reports.py             # Date ranges, totals, Matplotlib charts, guest summaries
│   ├── static/
│   │   ├── app.js                 # Frontend application script (CRUD, edit, guest mode, Excel modal)
│   │   └── style.css              # Financial dashboard stylesheet with guest banner & import modal
│   └── templates/
│       ├── admin.html             # Admin user management & stats dashboard
│       ├── index.html             # Personal & Guest expense tracker dashboard
│       ├── login.html             # User login page with Continue as Guest trial button
│       ├── profile.html           # User profile & password management page
│       └── register.html          # User registration page
├── data/
│   └── tracker.db                 # Local development SQLite database
├── scripts/
│   ├── init_turso_db.py           # Remote Turso schema initialization utility
│   └── migrate_sqlite_to_turso.py # SQLite-to-Turso data migration utility
└── tests/
    ├── conftest.py                # Pytest fixtures (authenticated client, admin_client, unauth_client)
    ├── test_api.py                # Core expense API and endpoint tests
    ├── test_auth_rbac.py          # Multi-user, RBAC, IDOR, and auth tests
    ├── test_excel.py              # Excel import, export, formatting, and security tests
    ├── test_guest_mode.py         # Guest trial, one-time restriction, isolation, and expiry tests
    ├── test_migration.py          # Data migration utility tests
    └── test_turso_db.py           # Turso db abstraction & security tests
```
