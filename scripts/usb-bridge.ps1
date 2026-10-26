<#
.SYNOPSIS
    Tunnels the telemetry bridge to an Android device over USB with `adb reverse`.

.DESCRIPTION
    `adb reverse tcp:8090 tcp:8090` makes 127.0.0.1:8090 *on the phone* connect to 127.0.0.1:8090
    *on this PC*, through the USB debugging connection. The phone app is the client, so this is
    `adb reverse`, not `adb forward` (forward is the opposite direction: PC -> phone).

    The mapping disappears whenever the cable is replugged or adb restarts. With -Watch the script
    re-applies it automatically, so you can leave it running next to the host.

.EXAMPLE
    .\scripts\usb-bridge.ps1 -Watch
.EXAMPLE
    .\scripts\usb-bridge.ps1 -Port 9000 -Serial R58N123ABC
.EXAMPLE
    .\scripts\usb-bridge.ps1 -Remove
#>
[CmdletBinding()]
param(
    [int]$Port = 8090,
    [string]$Serial,
    [switch]$Watch,
    [int]$IntervalSeconds = 3,
    [switch]$Remove
)

function Find-Adb {
    $onPath = Get-Command adb -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $roots = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, (Join-Path $env:LOCALAPPDATA 'Android\Sdk'))
    foreach ($root in $roots) {
        if ($root) {
            $candidate = Join-Path $root 'platform-tools\adb.exe'
            if (Test-Path $candidate) { return $candidate }
        }
    }
    return $null
}

function Invoke-Adb([string[]]$Arguments) {
    # Native stderr must not become a terminating error under Windows PowerShell 5.1.
    $ErrorActionPreference = 'Continue'
    $prefix = @()
    if ($Serial) { $prefix = @('-s', $Serial) }
    $output = & $script:Adb @prefix @Arguments 2>&1 | ForEach-Object { "$_" }
    [pscustomobject]@{ Code = $LASTEXITCODE; Output = ($output -join "`n").Trim() }
}

function Sync-Tunnel {
    $state = Invoke-Adb @('get-state')
    if ($state.Code -ne 0 -or $state.Output -ne 'device') {
        if ($state.Output -match 'more than one') { return 'several devices connected: pass -Serial (see `adb devices`)' }
        if ($state.Output -match 'unauthorized') { return 'device unauthorized: accept the USB debugging prompt on the phone' }
        return 'waiting for a device (USB debugging enabled and cable connected?)'
    }
    $list = Invoke-Adb @('reverse', '--list')
    if ($list.Output -match "tcp:$Port\s+tcp:$Port") { return 'ok' }
    $set = Invoke-Adb @('reverse', "tcp:$Port", "tcp:$Port")
    if ($set.Code -ne 0) { return "adb reverse failed: $($set.Output)" }
    return 'created'
}

$script:Adb = Find-Adb
if (-not $script:Adb) {
    Write-Error 'adb not found. Install Android SDK Platform-Tools and put it on PATH (docs/SETUP.md, step 4).'
    exit 1
}

if ($Remove) {
    $result = Invoke-Adb @('reverse', '--remove', "tcp:$Port")
    if ($result.Code -eq 0) { Write-Host "Removed tunnel tcp:$Port" } else { Write-Host $result.Output }
    exit $result.Code
}

$last = ''
do {
    $status = Sync-Tunnel
    if ($status -ne $last) {
        $stamp = Get-Date -Format 'HH:mm:ss'
        switch ($status) {
            'created' { Write-Host "$stamp  tunnel up: phone 127.0.0.1:$Port -> PC 127.0.0.1:$Port" -ForegroundColor Green }
            'ok'      { Write-Host "$stamp  tunnel active (tcp:$Port)" -ForegroundColor Green }
            default   { Write-Host "$stamp  $status" -ForegroundColor Yellow }
        }
        $last = $status
    }
    if ($Watch) { Start-Sleep -Seconds $IntervalSeconds }
} while ($Watch)

if ($status -in @('ok', 'created')) { exit 0 } else { exit 1 }
