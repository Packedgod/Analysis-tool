@echo off
setlocal

set "PROJECT=C:\Users\Admin\Documents\Codex\2026-07-13\git\Vibe-Analysis"
set "WATCHDOG=%PROJECT%\scripts\analysis_watchdog.ps1"
set "PID_FILE=%PROJECT%\.runtime\watchdog.pid"

for /f "delims=" %%U in ('whoami.exe') do set "CURRENT_IDENTITY=%%U"
echo %CURRENT_IDENTITY% | findstr.exe /I "CodexSandbox" >nul
if not errorlevel 1 (
  echo This launcher cannot access financial data when run inside Codex.
  echo Open File Explorer and double-click Start Vibe Analysis.cmd instead.
  exit /b 2
)

if not exist "%WATCHDOG%" (
  echo The Vibe Analysis watchdog is missing.
  pause
  exit /b 1
)

if exist "%PID_FILE%" (
  for /f "usebackq delims=" %%P in ("%PID_FILE%") do taskkill.exe /PID %%P /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat.exe -ano ^| findstr.exe /R /C:":8900 .*LISTENING"') do taskkill.exe /PID %%P /F >nul 2>&1

start "Vibe Analysis recovery service" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%WATCHDOG%"

echo Starting Vibe Analysis...
for /L %%I in (1,1,120) do (
  curl.exe -fsS --noproxy "*" http://127.0.0.1:8900/health >nul 2>&1 && goto ready
  ping.exe 127.0.0.1 -n 2 -w 1000 >nul
)

echo Vibe Analysis did not start. Review %PROJECT%\logs\server.err.log
pause
exit /b 1

:ready
echo Vibe Analysis is ready. Opening the research workspace...
start "" http://127.0.0.1:8900/
endlocal
exit /b 0
