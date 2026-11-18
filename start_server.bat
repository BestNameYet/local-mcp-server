@echo off
setlocal enabledelayedexpansion
title Local MCP Server Launcher ^& Salient Status Verifier

:: Always run in the repository directory
cd /d "%~dp0"

cls
echo ============================================================================
echo                     LOCAL MCP SERVER ^& CLOUDFLARE TUNNEL
echo                       Salient Status ^& Health Launcher
echo ============================================================================
echo.

:: -----------------------------------------------------------------------------
:: 1. Load configuration from .env if present
:: -----------------------------------------------------------------------------
if exist ".env" (
    echo [CONFIG] Loading environment configuration from .env...
    for /f "usebackq eol=# tokens=1* delims==" %%a in (".env") do (
        set "k=%%a"
        set "v=%%b"
        if not "!k!"=="" (
            if not "!v!"=="" set "!k!=!v!"
        )
    )
)

if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=8000
if "%CLOUDFLARE_TUNNEL_URL%"=="" set CLOUDFLARE_TUNNEL_URL=https://mcp.x9zk7mp4vn8w.dpdns.org/mcp
if "%CLOUDFLARE_TUNNEL_NAME%"=="" set CLOUDFLARE_TUNNEL_NAME=30664c83-c67c-4f6f-a8ad-3416fbd3802a

:: -----------------------------------------------------------------------------
:: 2. Identify & Verify Python Runtime
:: -----------------------------------------------------------------------------
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
    set "PYTHON_ENV=Local Virtualenv (.venv)"
) else (
    set "PYTHON_EXE=python"
    set "PYTHON_ENV=System PATH"
)

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python executable not found at "%PYTHON_EXE%".
    echo Please ensure Python or .venv is installed properly.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do set "PY_VER=%%v"
echo [STATUS] Python Runtime: %PY_VER% [%PYTHON_ENV%]

:: -----------------------------------------------------------------------------
:: 3. Check / Start Cloudflare Tunnel (cloudflared)
:: -----------------------------------------------------------------------------
echo.
echo [CHECK 1/3] Cloudflare Tunnel Status...

:: Locate cloudflared binary
set "CLOUDFLARED_BIN="
where cloudflared >nul 2>&1
if not errorlevel 1 (
    set "CLOUDFLARED_BIN=cloudflared"
) else if exist "C:\Program Files (x86)\cloudflared\cloudflared.exe" (
    set "CLOUDFLARED_BIN=C:\Program Files (x86)\cloudflared\cloudflared.exe"
) else if exist "C:\Program Files\cloudflared\cloudflared.exe" (
    set "CLOUDFLARED_BIN=C:\Program Files\cloudflared\cloudflared.exe"
) else if exist "%LOCALAPPDATA%\cloudflared\cloudflared.exe" (
    set "CLOUDFLARED_BIN=%LOCALAPPDATA%\cloudflared\cloudflared.exe"
)

:: Check if cloudflared.exe process is already active
set "CF_PID="
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq cloudflared.exe" /nh 2^>nul ^| find /i "cloudflared.exe"') do (
    set "CF_PID=%%p"
)

if not "!CF_PID!"=="" (
    echo   [PASS] cloudflared.exe is RUNNING (PID: !CF_PID!)
    echo          Tunnel ID: %CLOUDFLARE_TUNNEL_NAME%
) else (
    echo   [INFO] cloudflared.exe is not currently running. Attempting auto-boot...
    if not "%CLOUDFLARED_BIN%"=="" (
        if not "%CLOUDFLARE_TUNNEL_TOKEN%"=="" (
            echo   [INFO] Booting Cloudflare Tunnel using token...
            start "Cloudflare Tunnel (cloudflared)" /min "%CLOUDFLARED_BIN%" tunnel run --token %CLOUDFLARE_TUNNEL_TOKEN%
            timeout /t 3 /nobreak >nul
        ) else if not "%CLOUDFLARE_TUNNEL_NAME%"=="" (
            echo   [INFO] Booting Cloudflare Tunnel "%CLOUDFLARE_TUNNEL_NAME%"...
            start "Cloudflare Tunnel (cloudflared)" /min "%CLOUDFLARED_BIN%" tunnel run %CLOUDFLARE_TUNNEL_NAME%
            timeout /t 3 /nobreak >nul
        ) else if exist "%USERPROFILE%\.cloudflared\config.yml" (
            echo   [INFO] Booting Cloudflare Tunnel using config.yml...
            start "Cloudflare Tunnel (cloudflared)" /min "%CLOUDFLARED_BIN%" tunnel run
            timeout /t 3 /nobreak >nul
        )
    ) else (
        echo   [WARN] cloudflared executable not found on standard paths.
    )
)

:: -----------------------------------------------------------------------------
:: 4. Check / Start Local Uvicorn ASGI Server
:: -----------------------------------------------------------------------------
echo.
echo [CHECK 2/3] Local MCP Server Status (%HOST%:%PORT%)...

"%PYTHON_EXE%" -c "import socket; s = socket.socket(); s.settimeout(0.5); exit(0 if s.connect_ex(('%HOST%', int('%PORT%'))) == 0 else 1)" >nul 2>&1
if not errorlevel 1 (
    echo   [PASS] Server is LISTENING on http://%HOST%:%PORT%/mcp
) else (
    echo   [INFO] Server is down. Booting Uvicorn in a companion console window...
    start "Local MCP Server (Uvicorn)" cmd /k "title Local MCP Server (Uvicorn) && cd /d "%~dp0" && call "%PYTHON_EXE%" -m uvicorn server:app --host %HOST% --port %PORT% --reload"
    echo   [INFO] Waiting for port %PORT% to initialize...
)

:: -----------------------------------------------------------------------------
:: 5. Execute Salient Status Verifier & Render Dashboard
:: -----------------------------------------------------------------------------
echo.
echo [CHECK 3/3] Running End-to-End Salient Status Verifier...
"%PYTHON_EXE%" "%~dp0verify_server.py" --host %HOST% --port %PORT% --tunnel-url "%CLOUDFLARE_TUNNEL_URL%"
set "VERIFY_EXIT=%ERRORLEVEL%"

echo.
echo ============================================================================
if "%VERIFY_EXIT%"=="0" (
    echo                        ENDPOINT QUICK-CONNECT GUIDE
    echo ============================================================================
    echo   * Public Tunnel URL: %CLOUDFLARE_TUNNEL_URL%
    echo   * Local URL:         http://%HOST%:%PORT%/mcp
    echo   * Server Mode:       Stateless Streamable HTTP (/mcp)
    echo   * Hot-Reload:        ENABLED (edits to server.py reload live)
    echo.
    echo   To connect Claude Desktop, Cursor, or any MCP client, use this URL:
    echo     "%CLOUDFLARE_TUNNEL_URL%"
) else (
    echo                    [ACTION REQUIRED] SOME CHECKS FAILED
    echo ============================================================================
    echo   Review the check items marked [FAIL] in the dashboard above.
    echo   - If Local Server failed: verify the 'Local MCP Server (Uvicorn)' window.
    echo   - If Tunnel failed: verify cloudflared is running and DNS is active.
)
echo ============================================================================
echo.
echo Press any key to exit this launcher window (server continues running in background)...
pause >nul
