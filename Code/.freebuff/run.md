# FairShare — Live Preview Run Doc

## Reproduce the uncommitted artifacts

A fresh checkout needs nothing copied by hand — there are **no env files** (no `.env`, `.env.local`, etc.) and the app has no build step.

1. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   (Flask >= 3.0.0, Werkzeug >= 3.0.0, pytest >= 8.0.0)

2. The SQLite database `data/fairshare.db` is **self-seeding**: `main.py` calls `init_db()` at import time, which creates all tables and seeds demo users (`admin` / `admin123`, plus members `alice`, `bob`, `charlie` with password `password123`) if absent. No manual DB step required.

## Run the server

```bash
python main.py
```

- Serves on **http://127.0.0.1:5000/** (Flask debug mode, port 5000 as configured in the `if __name__ == '__main__'` block of `main.py`).
- If port 5000 is already taken by another instance of this project, reuse it (the page is identical) or start on a free port with `python -c "from main import app; app.run(debug=True, port=5001)"`.

Demo logins:
- Admin: `admin` / `admin123`
- Member: `alice` / `password123`
