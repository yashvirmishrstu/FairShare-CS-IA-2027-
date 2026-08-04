"""
=============================================================================
 SMOKE TESTS - DEV-SERVER AUTO-RELOADER
=============================================================================
 These tests guard a specific regression: if the Flask server is launched
 with use_reloader=False (or an older process is still running), the app
 silently serves STALE code - new routes added to main.py are never
 registered, and templates referencing them crash with a BuildError.

 Two independent checks cover both the source and the running process:

  1. STATIC SOURCE GUARD (runs everywhere, including CI)
     main.py's `if __name__ == '__main__':` launch block must keep
     debug=True (which makes Werkzeug default use_reloader=True) and must
     never pass use_reloader=False. If a future commit disables the
     reloader, this test fails immediately - no server needed.

  2. LIVE LOG MARKER (runs when a preview log exists)
     The most recently modified .freebuff/preview-*.log must contain
     Werkzeug's reloader startup signature ('* Restarting with stat').
     A process launched with use_reloader=False never prints it. The test
     skips when no preview log exists (e.g. a fresh checkout), so the suite
     stays green while still flagging a stale local server.

 IB HL CS: this is *verification* - static analysis (reading the launch
 block) plus a runtime probe (inspecting the server log), the same pairing
 a CI pipeline uses to catch configuration drift.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _main_run_block():
    """Return the COMMENT-STRIPPED text of main.py's launch block.

    Comments are removed first so that a remark like "never set
    use_reloader=False here" cannot trip the guard below (the check must
    reflect what the code DOES, not what a comment SAYS).
    """
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    marker = "if __name__ == '__main__':"
    assert marker in src, "main.py launch block not found"
    block = src.split(marker, 1)[1]
    # Drop full-line and trailing '# ...' comments (but not inside strings;
    # good enough for a launch block that contains no string literals).
    block = re.sub(r"#[^\r\n]*", "", block)
    return block


def test_main_launch_block_keeps_auto_reloader_enabled():
    """main.py must boot with debug=True and never disable the reloader.

    debug=True makes Werkzeug default use_reloader=True, so editing any .py
    file restarts the server automatically. Passing use_reloader=False (or
    dropping debug) would serve stale code after edits - the exact cause of
    the BuildError incident - so this guard fails the suite instead.
    """
    block = _main_run_block()

    assert not re.search(r"use_reloader\s*=\s*False", block), (
        "main.py disables the auto-reloader with use_reloader=False - "
        "remove it so route edits auto-reload during development."
    )
    assert re.search(r"debug\s*=\s*True", block), (
        "main.py must launch with debug=True so the auto-reloader "
        "is enabled by default."
    )


def test_preview_server_log_shows_reloader_marker():
    """The running preview server must have booted WITH the reloader.

    Werkzeug's reloader prints '* Restarting with stat' to the server log at
    startup; a process launched with use_reloader=False never prints it.
    Skips when no preview log exists (fresh checkout / CI), where the static
    source guard above remains the active check.
    """
    logs = sorted(ROOT.glob(".freebuff/preview-*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        pytest.skip("no .freebuff/preview-*.log found - nothing to check")

    # Newest log belongs to the currently relevant server process.
    log_text = logs[-1].read_text(encoding="utf-8", errors="replace")
    assert "Restarting with stat" in log_text, (
        f"{logs[-1].name} shows no reloader marker - the server was launched "
        "with use_reloader=False and will silently serve stale code. Restart "
        "it with `python main.py` (debug=True enables the reloader)."
    )
