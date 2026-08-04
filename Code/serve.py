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
    # config.py deliberately has NO hardcoded SECRET_KEY fallback (deploy
    # safety). Refusing to start here is the fail-closed behaviour: an
    # operator who forgets the key gets a clear message instead of an app
    # that signs sessions with a predictable default.
    if not os.environ.get('SECRET_KEY'):
        print("ERROR: SECRET_KEY environment variable is required.", file=sys.stderr)
        print('Generate one with: python -c "import secrets; print(secrets.token_hex(32))"', file=sys.stderr)
        sys.exit(1)

    # Import AFTER the secret check: importing main imports config, which
    # fails closed at import time when SECRET_KEY is missing (VULN-001 fix).
    # Checking first lets serve.py print its own friendly message instead of
    # surfacing config.py's RuntimeError traceback.
    from waitress import serve
    from main import app

    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))

    print(f"FairShare serving on http://{host}:{port} (waitress, debug OFF)")
    serve(app, host=host, port=port, threads=8)


if __name__ == '__main__':
    main()
