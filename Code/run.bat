@echo off
REM ===========================================================================
REM FairShare launcher (Windows cmd)
REM ---------------------------------------------------------------------------
REM Starts the Flask app with debug mode + the auto-reloader on a free port.
REM Port selection lives in main.py's launch block, so run.bat, run.sh, and
REM plain `python main.py` all behave identically.
REM
REM Usage:
REM   run.bat                  default port 5000, or the first free port
REM   run.bat 8080             force a specific port (falls back if busy)
REM
REM Note: a PORT variable set by the environment is cleared here so every
REM launch behaves the same - use the argument form to pin a port.
REM ===========================================================================
cd /d "%~dp0"

where python >/dev/null 2>&1
if errorlevel 1 (
    echo ERROR: 'python' not found on PATH.
    exit /b 1
)

set "PORT="

REM SECRET_KEY is REQUIRED and the app fails closed without it (no public
REM fallback). For local development generate a fresh random key per launch
REM if the caller did not supply one. A real deployment must set its own.
if not defined SECRET_KEY (
    for /f "delims=" %%i in ('python -c "import secrets; print(secrets.token_hex(32))"') do set "SECRET_KEY=%%i"
    echo Note: SECRET_KEY was not set - generated a fresh random key for this session.
)

REM Demo accounts (alice/bob/charlie/diana + marketplace data) are OPT-IN so
REM a public deployment is never seeded with documented passwords. Local
REM development wants them, so default to enabled here; a production deploy
REM should NOT set SEED_DEMO_DATA.
if not defined SEED_DEMO_DATA set "SEED_DEMO_DATA=1"

echo Starting FairShare (debug + auto-reloader) - press Ctrl+C to stop.
python main.py %*
