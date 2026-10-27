@echo off
title CS2 Telemetry Host
cd /d "%~dp0"

echo CS2 Telemetry Host
echo ==================
echo.

:: USB tunnel (the host also retries every 60 s automatically)
adb reverse tcp:8090 tcp:8090 2>nul && (
    echo [OK] USB tunnel active  ^(adb reverse tcp:8090 tcp:8090^)
) || (
    echo [--] Phone not connected yet -- plug in USB cable; tunnel restores automatically.
)
echo.

:: Start host (passes any extra args through, e.g. --log-level DEBUG)
C:\Users\danechka\AppData\Local\Programs\Python\Python314\python.exe -m telemetry_host %*

pause
