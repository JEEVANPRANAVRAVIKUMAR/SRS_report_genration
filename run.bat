@echo off
TITLE SRS Solar Daily Log - Production Service
echo ========================================================
echo SRS Solar Daily Log - M/s. SRS KUMARAN INDIA PVT LTD
echo Antichettipalayam 1 MW Solar Plant
echo ========================================================

:: Change to script directory
cd /d "%~dp0"

:: Set environment defaults if not defined
if not defined PORT set PORT=8000
if not defined TIMEZONE set TIMEZONE=Asia/Kolkata

:: Initialize database schema and seeds
echo Initializing database...
python -m app.cli init-db
if %ERRORLEVEL% neq 0 (
    echo Error initializing database.
    pause
    exit /b %ERRORLEVEL%
)

:RUN_LOOP
echo Starting SRS Solar Web Server on http://127.0.0.1:%PORT%...
python -m app.web.app
echo Server process exited with code %ERRORLEVEL%. Restarting in 5 seconds...
timeout /t 5 /nobreak
goto RUN_LOOP
