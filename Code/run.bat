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
echo Starting FairShare (debug + auto-reloader) - press Ctrl+C to stop.
python main.py %*
