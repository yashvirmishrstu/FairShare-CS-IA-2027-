# FairShare — Live Preview Run Doc

The application lives in the `Code/` subdirectory (Flask app: `Code/main.py`).

## Reproduce the uncommitted artifacts

A fresh checkout needs nothing copied by hand — there are **no env files** (no `.env`, `.env.local`, etc.) and the app has no build step.

1. Install Python dependencies from `Code/requirements.txt`:

   ```bash
   cd Code
   pip install -r requirements.txt
   ```

   (Flask >= 3.0.0, Werkzeug >= 3.0.0, pytest >= 8.0.0)

2. The SQLite database `Code/data/fairshare.db` is **self-seeding**: `main.py` calls `init_db()` at import time, which creates all tables and seeds demo users (`admin` / `admin123`, plus members `alice`, `bob`, `charlie` with password `password123`) if absent. No manual DB step required.

## Run the server

```bash
cd Code
python main.py
```

- Serves on **http://127.0.0.1:5000/** (Flask debug mode, port 5000 as configured in the `if __name__ == '__main__'` block of `main.py`).
- If port 5000 is already taken by another instance of this project, start on a free port instead, e.g.:

  ```bash
  cd Code
  python -c "from main import app; app.run(host='127.0.0.1', port=5001, debug=True, use_reloader=False)"
  ```

Demo logins:
- Admin: `admin` / `admin123`
- Member: `alice` / `password123`
