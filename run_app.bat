@echo off
title MedTrack Healthcare Platform
echo ===================================================
echo   Starting MedTrack Healthcare Platform
echo ===================================================
echo.
echo 1. Launching local web server on port 5000...
echo 2. Opening default browser at http://127.0.0.1:5000
echo.
start "" "http://127.0.0.1:5000"
python app.py
if errorlevel 1 (
    echo.
    echo Python failed to launch. Trying 'py app.py'...
    py app.py
)
pause
