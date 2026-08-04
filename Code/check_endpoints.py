"""
=============================================================================
 ENDPOINT HEALTH CHECK - catches stale-server BuildError instantly
=============================================================================
 This tiny script exists because of a real incident: the running preview
 server was executing an OLD copy of main.py (started before the
 member_coupon_redeem route was added). The on-disk templates referenced
 the new endpoint, so every render of that page crashed with:

     werkzeug.routing.exceptions.BuildError:
       Could not build url for endpoint 'member_coupon_redeem'

 This script performs TWO checks:

  1. STATIC CHECK (always): imports the CURRENT app from main.py, builds the
     set of registered endpoint names from app.url_map, then scans every
     Jinja template and main.py for url_for('...') references and verifies
     each endpoint exists. A missing endpoint is reported with the exact
     file:line - this is the code-level form of the BuildError.

  2. LIVE CHECK (--live): probes the RUNNING server at each registered
     route URL. Flask returns HTTP 404 for a URL that is NOT in the running
     app's URL map. So if the static check passes but the live server 404s
     a route the current code defines, the server process is STALE and
     simply needs a restart - the exact incident above.

 IB HL CS: this is an example of *verification & validation* - a static
 analysis pass (no server needed) plus a runtime integration probe,
 mirroring how a CI pipeline or health-check endpoint guards a deployment.

 Usage:
     python check_endpoints.py                # static check only
     python check_endpoints.py --live         # static + probe local server
     python check_endpoints.py --live http://127.0.0.1:5001
"""
import argparse
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# config.py fails closed without a SECRET_KEY (VULN-001 fix). This is a dev
# health-check tool that imports the app for its URL map; a throwaway key is
# fine for static analysis.
os.environ.setdefault("SECRET_KEY", "check-endpoints-harness-dev-key")

# Regex matching url_for('endpoint', ...) and url_for("endpoint", ...)
# in both Python (main.py) and Jinja ({{ url_for('x') }}) contexts.
URL_FOR_RE = re.compile(r"url_for\(\s*['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]")

# Files to scan for endpoint references.
SOURCES = [ROOT / "main.py", *sorted((ROOT / "templates").rglob("*.html"))]


def registered_endpoints():
    """Import the CURRENT app and return the set of registered endpoint names."""
    import main  # noqa: F401 - triggers route registration at import time
    return {rule.endpoint for rule in main.app.url_map.iter_rules()}


def static_check():
    """Scan sources for url_for references; return list of (file, line, endpoint)."""
    missing = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in URL_FOR_RE.finditer(text):
            endpoint = match.group(1)
            if endpoint not in registered_endpoints():
                line_no = text[: match.start()].count("\n") + 1
                try:
                    rel = path.relative_to(ROOT)
                except ValueError:
                    rel = path  # outside the project root - show absolute path
                missing.append((rel, line_no, endpoint))
    return missing


def live_check(base_url, timeout=5):
    """Probe the running server; return list of (endpoint, path, status).

    For routes with URL parameters we substitute a placeholder value so the
    URL is syntactically valid - we only care about the *status code*, not
    the response body. 404 means the running app has no such route (stale
    server); 3xx/405 mean the route exists (auth redirects / method checks).
    """
    import main  # noqa: F401
    problems = []
    seen = set()
    for rule in main.app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        # Convert Flask rule '/admin/checkout/<int:checkin_id>' -> a real URL.
        url_path = re.sub(r"<(?:\w+:)?(\w+)>", "1", rule.rule)
        url = base_url.rstrip("/") + url_path
        key = (rule.endpoint, url_path)
        if key in seen:
            continue
        seen.add(key)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fairshare-healthcheck"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
        except urllib.error.HTTPError as err:
            status = err.code
        except Exception as err:  # connection refused, DNS, timeout...
            problems.append((rule.endpoint, url_path, "UNREACHABLE (%s)" % err))
            continue

        if status == 404:
            problems.append((rule.endpoint, url_path, "404 - route missing on running server (STALE SERVER, restart it)"))
        elif status >= 500:
            problems.append((rule.endpoint, url_path, "%d - server error" % status))
    return problems


def main():
    parser = argparse.ArgumentParser(description="Verify all url_for endpoints resolve.")
    parser.add_argument("--live", nargs="?", const="http://127.0.0.1:5000", metavar="URL",
                        help="Also probe the running server at URL (default http://127.0.0.1:5000)")
    args = parser.parse_args()

    endpoints = registered_endpoints()
    missing = static_check()

    total_refs = 0
    for p in SOURCES:
        total_refs += len(URL_FOR_RE.findall(p.read_text(encoding="utf-8", errors="replace")))
    print("Registered endpoints (fresh import): %d" % len(endpoints))
    print("Scanned url_for references: %d" % total_refs)
    print()

    if missing:
        print("FAIL - %d url_for reference(s) point to missing endpoints:" % len(missing))
        for rel, line, endpoint in missing:
            print("  %s:%d  -> url_for('%s')" % (rel, line, endpoint))
        print()
        print("Fix: the endpoint is not defined in main.py (or is misspelled).")
        sys.exit(1)

    print("PASS - every url_for endpoint resolves in the current code.")

    if args.live:
        print()
        print("Probing running server at %s ..." % args.live)
        problems = live_check(args.live)
        if problems:
            print("FAIL - %d route problem(s) on the running server:" % len(problems))
            for endpoint, path, detail in problems:
                print("  %s  (%s)  %s" % (path, endpoint, detail))
            print()
            print("Most likely cause: the server is running STALE code.")
            print("Restart it:  python main.py   (or the preview server)")
            sys.exit(1)
        print("PASS - every route answers on the running server (no stale-server 404s).")


if __name__ == "__main__":
    main()
