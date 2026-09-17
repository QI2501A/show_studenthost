@echo off
setlocal
cd /d "%~dp0"
title Show Host

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3 from https://python.org and try again.
    pause
    exit /b 1
)

if not exist venv (
    echo Setting up Python environment ^(first run only^)...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        pause
        exit /b 1
    )
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

echo.
echo NOTE: start hub_dashboard\RUN.bat first, in its own window, so IGNITE can
echo actually reach the robots. Without it the show still runs, narration-only.
echo.
echo This listens on the microphone and responds as the student speaks each
echo line — no Enter key needed. OVERRIDE is different: the student types it
echo into THIS window when the system goes rogue, matching the show's own
echo story of returning to the terminal. If the mic isn't available, student
echo lines fall back to the operator pressing Enter instead.
echo.
echo Starting the show — press Ctrl+C to stop.
echo.
python Dialogue.py
echo.
pause
