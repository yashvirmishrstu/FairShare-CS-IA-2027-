# Deploying FairShare on Vercel

Vercel natively detects this Flask app: it looks for a `Flask` instance named
`app` in `main.py` (a supported entrypoint), so no `api/index.py` or WSGI
shim is needed.

## What's already configured

- `vercel.json` — declares `main.py` as the function entrypoint.
- `public/static/` — the CSS/JS live here (moved from `static/`). Vercel
  serves every file under `public/**` from its CDN at the matching URL path,
  so the existing `/static/...` URLs in the templates work unchanged. Locally,
  Flask serves the same files via `static_folder='public/static'`.
- `config.py` — when Vercel sets `VERCEL=1`, SQLite is created in `/tmp`
  (serverless filesystems are read-only outside `/tmp`).
- `database.py` — a sqlite3-compatible adapter (`_TursoConnection`) lets the
  whole app run against a **hosted SQLite database (Turso)** when `TURSO_URL`
  is set, so no app code changes are needed for persistent storage.

## Deploy steps

1. Push this branch to your Git host and import the repo in the
   [Vercel dashboard](https://vercel.com/new) (framework: **Other** — Flask
   detection happens automatically).

2. **Set the `SECRET_KEY` environment variable** (required — the app fails
   closed without it). Generate a value with:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   and add it under **Project Settings → Environment Variables** (add it for
   Production, Preview, and Development). Never commit the value.

3. Deploy. Or use the CLI (`vercel` / `vc deploy`, CLI >= 48.2.10), which
   reads `SECRET_KEY` from your local environment / `.env`.

4. Test locally first with `vercel dev` after `pip install -r requirements.txt`.

## Persistent data on Vercel (Turso)

By default the app stores data in a local SQLite file, which a serverless
filesystem cannot keep — it is read-only outside `/tmp`, and `/tmp` resets
per instance, so everything is recreated (with seeded demo data) on each cold
start. To make data survive, point the app at **Turso**, a hosted
SQLite-compatible database (libSQL is a SQLite fork, so the project's SQL —
triggers, `date('now')`, `strftime`, `PRAGMA table_info` migrations,
`AUTOINCREMENT`, `BEGIN IMMEDIATE` transactions — works unchanged):

### Easiest: one-click Vercel Marketplace integration

Install **Turso Cloud** from the [Vercel Marketplace](https://vercel.com/marketplace/tursocloud)
— connect your Turso account, pick or create a database, and the integration
provisions `TURSO_URL` + `TURSO_AUTH_TOKEN` into the project's environment
variables automatically (no tokens to copy, no secrets to store).

The deploy workflow **enforces** this: the deploy job fails with a message
pointing at the marketplace until those two variables exist for production,
so the site can never silently run on ephemeral storage. It also smoke-tests
the live URL after every deploy.

### Manual alternative (Turso CLI / dashboard)

1. Create a database (dashboard or `turso db create fairshare`). The free
   tier is fine for a demo.
2. Copy its connection URL — make sure it starts with **`libsql://`** (the
   WebSocket/Hrana scheme, which supports transactions). The `https://`
   scheme does **not** support transactions, and the code uses `BEGIN
   IMMEDIATE` for the coupon/receipt/revoke flows.
3. Create an auth token (`turso db tokens create fairshare`).
4. Add both as Vercel environment variables (or your local environment):
   - `TURSO_URL` = `libsql://<db>-<org>.turso.io`
   - `TURSO_AUTH_TOKEN` = `<token>`
5. Deploy. On the first request, `init_db()` runs automatically and creates
   + seeds the schema on the Turso database (it is idempotent, so every
   cold start is a harmless no-op).

The `libsql-client` dependency is already in `requirements.txt`. Nothing in
`models.py` or `main.py` changes — the adapter in `database.py` exposes the
same sqlite3 cursor API.

**This network path is validated end-to-end.** `verify_turso_e2e.py` drives
the whole app (schema init + seeds, SQLite triggers, login hashes, guest-pass
lifecycle, receipts, coupon marketplace, transactions, cold-start survival)
against any `TURSO_URL`. It was run successfully against a local `sqld`
server — the exact server software Turso runs — over the Hrana/WebSocket
protocol:

```bash
# local sqld (WSL): run the same protocol Turso uses, no account needed
sqld --http-listen-addr 0.0.0.0:8080 --hrana-listen-addr 0.0.0.0:8081 \
     --db-path ~/sqld-demo/fairshare-demo.db
set TURSO_URL=ws://127.0.0.1:8081
python verify_turso_e2e.py
```

One real finding from that run: over the Hrana protocol a transaction is a
stream-state change, and raw `BEGIN IMMEDIATE` / `COMMIT` SQL text is ignored
by the server. The adapter therefore routes the app's `BEGIN IMMEDIATE`
flows through libsql's `transaction()` API, so the coupon/receipt/revoke
atomicity guarantees hold on hosted Turso too. (Use the `libsql://` URL —
the `https://` scheme does not support transactions.)

## Important caveats

- **Without `TURSO_URL`, data is ephemeral on Vercel** — see the Turso
  section above to enable persistence.
- **Credentials are no longer seeded with public defaults** (VULN-001
  fix): the initial `admin` password comes from the `ADMIN_PASSWORD`
  environment variable (or a strong one-time random password printed to the
  startup log), and the demo member accounts (`alice`, `bob`, `charlie`,
  `diana`) are only created when `SEED_DEMO_DATA=1` — leave it unset on a
  public deployment. Note: an **existing** database keeps its old accounts;
  delete `data/` to reseed a fresh, secured one.
- **Guest QR / camera** features need HTTPS — Vercel provides it by default.

## CI/CD: GitHub Actions

`.github/workflows/deploy.yml` (at the **repository root** — one level above
`Code/`) runs the full test suite on every push, and deploys to Vercel
(production) when the push lands on `vercel-deployment` — pushes to any
other branch run the tests only. To use it:

1. Set the Vercel project's **Root Directory** to `Code` (the app lives in
   that subdirectory of the repo) and set `SECRET_KEY` in the project's
   environment variables. Add `ADMIN_PASSWORD` (a strong value) for both the
   **Production** and **Preview** environments — and make sure
   `SEED_DEMO_DATA` is **not** set in any environment (see the guard below).
2. Add these **repository secrets** (Settings → Secrets and variables → Actions):
   - `VERCEL_TOKEN` — create at <https://vercel.com/account/tokens>
   - `VERCEL_ORG_ID` — your team ID (Team Settings → General)
   - `VERCEL_PROJECT_ID` — your project ID (Project Settings → General)
3. Push to `vercel-deployment`. The test job needs no secrets
   (tests/conftest.py supplies a test `SECRET_KEY`); the deploy job runs
   only after tests pass.

In addition to the test suite, the test job runs a **requirements
sync-check**: it fails the build if the repo-root `requirements.txt` (the
fallback for Vercel's default-root-directory build) and
`Code/requirements.txt` drift apart, so a new runtime dependency can't be
added to one without the other. `pytest` is the one intended difference —
it is test-only and stays out of the root copy.

**The deploy job enforces safe credentials before it deploys.** Before
building, it queries the Vercel env API and fails the run with a clear
`::error::` if: `TURSO_URL`/`TURSO_AUTH_TOKEN` are missing from the
production environment (one-click Turso setup), **`SEED_DEMO_DATA` is set in
any environment** (preview deployments can never get the demo
`alice`/`bob`/`charlie`/`diana` accounts — `SEED_DEMO_DATA=1` is strictly
opt-in, used only by the CI smoke job's throwaway local `sqld` and dev
sandboxes that set it explicitly), or
`ADMIN_PASSWORD` is absent from production/preview (so the admin never ends
up with a random, unrecoverable password). A misconfigured project therefore
fails the deploy instead of going live with demo accounts.
4. After a successful production deploy, a **smoke** job boots the whole app
   against a local `sqld` server (the software Turso runs) and drives the key
   routes — member/admin logins, facility scans, rewards, coupon claim, guest
   day-pass — through the Turso adapter, then HTTP-checks the live
   `VERCEL_URL`. Run it locally anytime with `python smoke_vercel.py`.

Manual deploys are available anytime via **Actions → Test & Deploy → Run
workflow**.
