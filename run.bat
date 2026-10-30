@echo off
setlocal
echo ========================================================
echo   Vera - Research that knows you, and proves it.
echo   Automated Test Build Launcher
echo ========================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist .env (
    if exist .env.example (
        echo [INFO] Creating .env from .env.example...
        copy .env.example .env >nul
        echo [ACTION REQUIRED] Please edit .env and insert your TOKEN_FACTORY_API_KEY and TAVILY_API_KEY.
        echo.
    )
)

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3.10+ is required but not found in PATH.
    echo Please install Python from https://www.python.org/
    pause
    exit /b 1
)

if not exist .venv (
    echo [INFO] Provisioning virtual environment in .venv...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo [INFO] Installing backend dependencies...
    pip install -r backend\requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

set "PYTHONPATH=%SCRIPT_DIR%backend;%PYTHONPATH%"

echo [INFO] Starting Vera unified server on http://127.0.0.1:8000 ...
echo [INFO] Opening browser in 3 seconds...
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"

python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Server exited with code %ERRORLEVEL%.
    pause
)
