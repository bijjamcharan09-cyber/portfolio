# Expense Tracker

A modern personal finance web application built with Flask, SQLite/Turso (hosted libSQL), vanilla HTML/CSS/JavaScript, and pytest. It supports income and expense tracking, category filtering, monthly/annual summaries, interactive Matplotlib charts, live currency conversions (via Frankfurter API), and seamless deployment to Vercel.

---

## Architecture Overview

| Environment | Database Layer | Storage Mode | Driver |
|---|---|---|---|
| **Local Development** | SQLite 3 | Local file (`data/tracker.db`) | Standard library `sqlite3` |
| **Automated Testing** | SQLite 3 | Isolated temporary file (`tmp_path / test.db`) | Standard library `sqlite3` |
| **Production (Vercel)** | Turso Cloud | Hosted SQLite-compatible libSQL | `turso_serverless` (pure Python PEP 249) / `libsql` |

- **Money Storage**: Handled strictly as integer cents (e.g. `12.50` stored as `1250`) to eliminate floating-point rounding errors.
- **SQL Security**: 100% parameterized queries using `?` placeholders across both local SQLite and remote Turso drivers.
- **Credential Safety**: Authentication tokens are never printed in logs or exposed in HTTP responses.

---

## Prerequisites & Supported Python Versions

- **Python**: Python 3.9, 3.10, 3.11, 3.12, 3.13, or 3.14 (supports Windows x86_64, Windows ARM64, macOS, and Linux).
- **Turso CLI** (optional, for managing Turso databases locally): [Install Turso CLI](https://docs.turso.tech/cli/introduction).
- **Vercel CLI** (optional, for CLI deployments): `npm i -g vercel`.

---

## Local Installation (Windows & macOS/Linux)

### 1. Clone the repository and enter the directory
```powershell
# Windows PowerShell
cd C:\Users\bijja\Portfolio-Showcase\web_project\expense_tracker
```

### 2. Create and activate a virtual environment
```powershell
# Windows PowerShell
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

To run locally with a local SQLite database:

1. Copy `.env.example` to `.env`:
   ```powershell
   # Windows PowerShell
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

4. Start the application:
   ```powershell
   python run.py
   ```
   Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

## Production Setup with Turso

[Turso](https://turso.tech) is an edge-hosted, SQLite-compatible database built on libSQL. It provides persistent storage for serverless environments where local file storage is ephemeral.

### 1. Create a Turso Database

1. Sign up or log in at [turso.tech](https://turso.tech) (or via the Turso CLI).
2. Using Turso CLI:
   ```bash
   turso auth login
   turso db create expense-tracker-db
   ```
   *(Or create a new database named `expense-tracker-db` via the Turso Web Console).*

### 2. Obtain Database URL and Authentication Token

Using Turso CLI:
```bash
# Show database URL (e.g., libsql://expense-tracker-db-<org>.turso.io)
turso db show expense-tracker-db --url

# Create an authentication token
turso db tokens create expense-tracker-db
```
*(Or navigate to your database in the Turso Dashboard > **Connect** > copy the **Database URL** and create a **Database Token**).*

### 3. Configure Local Environment for Turso (Optional Test)

In your `.env`:
```dotenv
DATABASE_MODE=turso
TURSO_DATABASE_URL=libsql://expense-tracker-db-<your-org>.turso.io
TURSO_AUTH_TOKEN=your-turso-auth-token-here
```

---

## Remote Schema Initialization

Before deploying or running on Turso for the first time, initialize the database schema on Turso. This process creates the `transactions` table and `idx_transactions_date` index idempotently without touching or dropping any data.

### Option A: Using the initialization script
```powershell
python scripts/init_turso_db.py --url "libsql://expense-tracker-db-<org>.turso.io" --token "your-token"
```
*(If `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are defined in your `.env`, simply run `python scripts/init_turso_db.py`)*

### Option B: Using the Flask CLI command
```powershell
flask --app run.py init-db
```

---

## Migrating Existing SQLite Data to Turso

If you have existing transactions in `data/tracker.db`, transfer them into Turso using the dedicated migration utility:

```powershell
python scripts/migrate_sqlite_to_turso.py --source data/tracker.db --url "libsql://expense-tracker-db-<org>.turso.io" --token "your-token"
```

### Safety Guarantees:
- **Non-Destructive**: Reads from `data/tracker.db` in read-only mode. Never deletes or alters the local file.
- **Idempotent**: Uses `INSERT OR IGNORE` preserving transaction IDs and `created_at` timestamps. Safe to rerun without duplicating records.
- **Integrity Verification**: Reports migrated counts, skipped counts, and validates the final row count on Turso.
- **Secret Redaction**: Never logs authentication tokens to standard output or error streams.

---

## Deployment to Vercel

Vercel provides serverless execution for Python applications. Because Vercel serverless functions have a read-only filesystem (except `/tmp`), Turso serves as the persistent cloud database.

### 1. Project Deployment Files

The project includes:
- `api/index.py`: Serverless WSGI entry point exposing the Flask `app`.
- `vercel.json`: URL rewrite configuration routing all traffic to `/api/index.py`.
- `requirements.txt`: Includes `turso_serverless>=0.1.0` (zero-dependency pure Python driver) and Flask dependencies.

### 2. Configure Environment Variables in Vercel

In your Vercel Project Dashboard (**Settings > Environment Variables**), set:

| Variable | Value | Description |
|---|---|---|
| `FLASK_ENV` | `production` | Enables production mode and strict security checks |
| `SECRET_KEY` | *(random 32+ char secret)* | Production session/cookie signing key |
| `DATABASE_MODE` | `turso` | Enforces Turso cloud database connection |
| `TURSO_DATABASE_URL` | `libsql://<db>-<org>.turso.io` | Your Turso database endpoint |
| `TURSO_AUTH_TOKEN` | *(your auth token)* | Your Turso database token |
| `BASE_CURRENCY` | `INR(₹)` *(or USD, EUR, etc.)* | Default currency code |
| `FLASK_DEBUG` | `0` | Disables debug mode in production |

### 3. Vercel Project Root Directory Setting

If you imported the parent repository (`Portfolio-Showcase`) into Vercel, configure the Root Directory:
- Go to **Project Settings > General > Root Directory**.
- Click **Edit** and set it to: `web_project/expense_tracker`.
- Save changes.

### 4. Deploy

#### Via Git (Recommended)
Push your repository to GitHub / GitLab / Bitbucket. Vercel will automatically trigger a build and deployment.

#### Via Vercel CLI
```powershell
cd web_project/expense_tracker
vercel --prod
```

---

## Running the Automated Test Suite

The test suite runs against an isolated, temporary SQLite database (`tmp_path / test.db`) to ensure tests remain fast, self-contained, and completely independent of external network access or production credentials.

```powershell
# Run all tests
pytest -v
```

### Test Coverage Highlights:
- Expense CRUD operations (creation, listing, retrieval, deletion).
- Input validation (amounts, types, categories, date formats).
- Reports, summaries, and Matplotlib chart generation.
- Production configuration validation (insecure secrets and missing Turso credentials are rejected).
- Safe error handling and token redaction.
- Migration utility idempotency and non-destructive source handling.

---

## Troubleshooting & Common Issues

### 1. `DATABASE_MODE is 'turso' but TURSO_DATABASE_URL is not set`
- **Cause**: The application is configured to connect to Turso, but no URL was found in the environment.
- **Solution**: Ensure `TURSO_DATABASE_URL` is set in your `.env` file (local) or in Vercel Environment Variables (production).

### 2. `TURSO_AUTH_TOKEN is required to authenticate with remote Turso database`
- **Cause**: A remote `libsql://` or `turso.io` URL was specified without an authentication token.
- **Solution**: Generate a token using `turso db tokens create <database-name>` and add it to `TURSO_AUTH_TOKEN`.

### 3. `Could not connect to Turso database: HTTP status 401: Unauthorized`
- **Cause**: The provided `TURSO_AUTH_TOKEN` is invalid, expired, or belongs to a different database.
- **Solution**: Issue a new token with `turso db tokens create <database-name>` and update `TURSO_AUTH_TOKEN`.

### 4. `Production requires a secure, non-default SECRET_KEY`
- **Cause**: In production (`FLASK_ENV=production` or running on Vercel), the default development fallback secret was detected.
- **Solution**: Set a strong, randomly generated `SECRET_KEY` in your environment.

### 5. `Matplotlib font cache / config permission denied`
- **Cause**: In serverless environments like Vercel, the home directory is read-only.
- **Solution**: Handled automatically in `app/config.py` by redirecting `MPLCONFIGDIR` to the system temporary directory (`/tmp/matplotlib`).

### 6. `Not Found: The requested URL was not found on the server`
- **Cause**: Vercel's catch-all rewrite forwards incoming requests to `/api/index`. Without path middleware, Flask receives `PATH_INFO = "/api/index"` instead of the user's original requested URL (`/`).
- **Solution**: Resolved by `VercelPathMiddleware` in `api/index.py` (which restores `PATH_INFO` from Vercel's `x-matched-path` header) and route aliases for `/api/index` in `app/__init__.py`. Ensure `vercel.json` maps to `/api/index` (without `.py`).

---

## Project Structure

```text
expense_tracker/
├── .env.example                  # Environment template
├── .gitignore                     # Git ignore rules (.env, *.db ignored)
├── pytest.ini                     # Pytest configuration
├── README.md                      # Documentation
├── requirements.txt               # Dependencies (Flask, turso_serverless, etc.)
├── run.py                         # Local development server entry point
├── vercel.json                    # Vercel deployment rewrites
├── api/
│   └── index.py                   # Vercel Serverless Function entry point
├── app/
│   ├── __init__.py                # App factory, CLI commands, security headers
│   ├── api.py                     # REST endpoints
│   ├── config.py                  # Centralized configuration & environment parsing
│   ├── db.py                      # Database abstraction (SQLite & Turso support)
│   ├── validators.py              # Input validation
│   ├── services/
│   │   ├── exchange.py            # Frankfurter currency exchange service
│   │   └── reports.py             # Date ranges, totals, Matplotlib charts
│   ├── static/
│   │   ├── app.js                 # Frontend application script
│   │   └── style.css              # Frontend stylesheets
│   └── templates/
│       └── index.html             # Single-page application HTML
├── data/
│   └── tracker.db                 # Local development SQLite database (12 existing records)
├── scripts/
│   ├── init_turso_db.py           # Remote Turso schema initialization utility
│   └── migrate_sqlite_to_turso.py # SQLite-to-Turso data migration utility
└── tests/
    ├── conftest.py                # Pytest fixtures (temporary test SQLite db)
    ├── test_api.py                # API and endpoint tests
    ├── test_migration.py          # Data migration utility tests
    └── test_turso_db.py           # Turso db abstraction & security tests
```
