@echo off
setlocal EnableDelayedExpansion
title Salient MCP Server ^& Cloudflare Tunnel Launcher (WSL2)

set "MCP_DIR=/home/samue/local-mcp-server"
set "PYTHON_BIN=/home/samue/local-mcp-server/.venv/bin/python"
set "UVICORN_APP=server:app"
set "HOST=127.0.0.1"
set "PORT=8000"
set "TUNNEL_ID=30664c83-c67c-4f6f-a8ad-3416fbd3802a"
set "VERIFY_SCRIPT=verify_server.py"

echo ============================================================================
echo   LAUNCHING SALIENT MCP SERVER ^& CLOUDFLARE TUNNEL IN WSL2
echo ============================================================================

echo [1/4] Stopping existing Uvicorn and cloudflared processes...
taskkill /F /IM cloudflared.exe >nul 2>&1
wsl -- bash -lc "pkill -f '[u]vicorn' || true; pkill -f '[c]loudflared' || true"
timeout /t 1 /nobreak >nul

echo [2/4] Starting persistent Uvicorn MCP Server (%HOST%:%PORT%)...
start "WSL2-Uvicorn-MCP" /min wsl -- bash -lc "cd %MCP_DIR% && exec %PYTHON_BIN% -m uvicorn %UVICORN_APP% --host %HOST% --port %PORT% > /tmp/uvicorn_mcp.log 2>&1"

echo [3/4] Starting persistent Cloudflare Tunnel (%TUNNEL_ID%)...
start "WSL2-Cloudflared" /min wsl -- bash -lc "exec cloudflared tunnel --protocol http2 --edge-ip-version 4 run %TUNNEL_ID% > /tmp/cloudflared.log 2>&1"

echo [4/4] Waiting 6 seconds for Uvicorn and Cloudflare Edge registration...
timeout /t 6 /nobreak >nul

echo.
wsl -- bash -lc "cd %MCP_DIR% && %PYTHON_BIN% %VERIFY_SCRIPT%"

echo.
pause
