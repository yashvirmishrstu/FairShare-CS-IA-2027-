"""
Full member -> guest -> fee -> voucher lifecycle, run as part of the suite.

verify_behavior.py is a standalone script that drives the real Flask app
against a throwaway seeded database and asserts every state transition in
the complete lifecycle (earn -> coupon claim -> fee credit -> voucher
redeem -> guest board/pay/leave -> dedup -> CSV exports). It exits non-zero
if any assertion fails.

This module wraps that script as a subprocess so the exact same assertions
run inside pytest (CI). A subprocess is deliberate: verify_behavior.py
bootstraps its own isolated temp database and imports the Flask app at
module scope, so importing it in-process would collide with pytest's own
per-test database fixtures (test_app.py / test_rewards.py monkeypatch
config.Config.DATABASE before importing main).
"""
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFIER = os.path.join(PROJECT_ROOT, "verify_behavior.py")


def test_full_lifecycle_verifier_passes():
    """The complete member/guest lifecycle satisfies every behavioral
    assertion in verify_behavior.py (fresh temp DB, isolated process)."""
    assert os.path.isfile(VERIFIER), f"verify_behavior.py not found at {VERIFIER}"

    result = subprocess.run(
        [sys.executable, "-u", VERIFIER],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    assert result.returncode == 0, (
        "verify_behavior.py lifecycle checks failed "
        f"(exit {result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    # Belt-and-braces: the verifier exits 0 implicitly on success and 1 on
    # failure, so the returncode check is sufficient today — the sentinel
    # guards against a future refactor returning 0 through another path.
    assert "ALL BEHAVIORAL CHECKS PASSED" in result.stdout, (
        "verify_behavior.py did not report a clean pass:\n"
        f"--- stdout ---\n{result.stdout}"
    )
