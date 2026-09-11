"""
================================================================================
 FAIRSHARE — PRODUCTION WSGI ENTRYPOINT (waitress)
================================================================================
 Runs the SAME Flask app behind the waitress production WSGI server with
 debug mode OFF. Use this (NOT `python main.py`) for any deployment that
 will be reached from another machine or shown to an audience.

 Usage:
     set SECRET_KEY=<long random value>     (REQUIRED - no hardcoded fallback)
     python serve.py                        (port 5000, all interfaces)
     set PORT=8080 && python serve.py       (choose a different port)
     set HOST=127.0.0.1 && python serve.py  (loopback only, e.g. for a demo)

 Generate a SECRET_KEY with:
     python -c "import secrets; print(secrets.token_hex(32))"

 IB HL CS: separation of concerns. main.py stays the DEVELOPMENT entrypoint
 (debug + auto-reloader for instant edits); serve.py is the PRODUCTION
 entrypoint (waitress, debug off, multi-threaded request handling). The two
 launch paths share the same app object, so behaviour is identical — only
 the server and debug flag differ.
"""
import os
import sys


def main():
    # Run the shared startup validation FIRST so the operator gets one
    # friendly message listing EVERY missing/unsafe setting (SECRET_KEY, and
    # on Vercel ADMIN_PASSWORD / SEED_DEMO_DATA / the Turso pair) instead of
    # a bare traceback. Importing main would run the same validator and fail
    # closed anyway, but checking here lets serve.py print a clean error and
    # exit 1 without one.
    from config import Config
    problems = Config.check_config()
    if problems:
        print("ERROR: FairShare cannot start -- configuration problems:", file=sys.stderr)
        for problem in problems:
            for line in problem.splitlines():
                print(f"  {line}", file=sys.stderr)
        print("Fix the problems above, then re-run.", file=sys.stderr)
        sys.exit(1)

    # Import AFTER validation succeeds.
    from waitress import serve
    from main import app

    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))

    print(f"FairShare serving on http://{host}:{port} (waitress, debug OFF)")
    serve(app, host=host, port=port, threads=8)


if __name__ == '__main__':
    main()
