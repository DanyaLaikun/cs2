@echo off
:: Build integrity_guard.dll
:: Tries Visual Studio 2022/2019 generators first, falls back to MinGW Makefiles.
:: The compiled DLL is copied to pc-host\telemetry_host\security\ automatically.

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "BUILD_DIR=%SCRIPT_DIR%build"

echo [*] Creating build directory...
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

:: --- Try MSVC generators in order ---
set "GENERATOR="
for %%G in ("Visual Studio 17 2022" "Visual Studio 16 2019") do (
    if "!GENERATOR!"=="" (
        cmake -S "%SCRIPT_DIR%" -B "%BUILD_DIR%" -G %%G -A x64 >nul 2>&1
        if !ERRORLEVEL!==0 set "GENERATOR=%%G"
    )
)

if "!GENERATOR!"=="" (
    echo [*] MSVC not found, trying MinGW Makefiles...
    cmake -S "%SCRIPT_DIR%" -B "%BUILD_DIR%" -G "MinGW Makefiles" ^
          -DCMAKE_BUILD_TYPE=Release
    if !ERRORLEVEL! NEQ 0 (
        echo [-] CMake configure failed.  Install MSVC or MinGW and ensure cmake is on PATH.
        exit /b 1
    )
    set "GENERATOR=MinGW Makefiles"
)

echo [+] Using generator: !GENERATOR!
echo [*] Building Release...
cmake --build "%BUILD_DIR%" --config Release
if %ERRORLEVEL% NEQ 0 (
    echo [-] Build failed.
    exit /b 1
)

:: --- Verify output ---
set "DLL_PATH="
for %%F in (
    "%BUILD_DIR%\Release\integrity_guard.dll"
    "%BUILD_DIR%\integrity_guard.dll"
) do (
    if "!DLL_PATH!"=="" if exist %%F set "DLL_PATH=%%F"
)

if "!DLL_PATH!"=="" (
    echo [-] DLL not found in expected output paths.
    exit /b 1
)

echo [+] Built: !DLL_PATH!

:: CMake POST_BUILD already copies to telemetry_host/security/, but copy
:: here too as a fallback for generators that skip post-build in --config Release.
set "DEST=%SCRIPT_DIR%..\telemetry_host\security\integrity_guard.dll"
copy /Y "!DLL_PATH!" "%DEST%" >nul
echo [+] Installed to: %DEST%

echo.
echo [+] Done.  Run tests with:
echo     cd ..\pc-host
echo     python -m pytest tests\test_integrity.py -v
