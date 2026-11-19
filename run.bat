@echo off
echo ========================================================
echo Starting HoseXperts Sales Analysis Dashboard...
echo ========================================================

cd /d "%~dp0"

if exist "..\Procurement_Dashboard\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=..\Procurement_Dashboard\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Using Python: %PYTHON_EXE%
echo Opening application at http://localhost:8000
echo Press Ctrl+C to stop the server.
echo.

"%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause
