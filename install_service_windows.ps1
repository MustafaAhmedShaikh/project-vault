# Registers the ProjectVault daemon as a per-user Scheduled Task that runs at logon.
# No administrator rights needed. Remove with uninstall_service_windows.bat.
$ErrorActionPreference = 'Stop'
$taskName  = 'ProjectVault_Daemon'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$daemon    = Join-Path $scriptDir 'vault_daemon.py'

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath $daemon)) { Fail "vault_daemon.py not found in $scriptDir" }

# Find a real python.exe (reject the Microsoft Store stub).
$pythonExe = $null
foreach ($cmd in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
    $p = $cmd.Source
    if (-not $p) { continue }
    if ($p -like '*\WindowsApps\*') {
        # Store stub or Store-installed python; accept only if it really runs.
        $out = & $p -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
    }
    $pythonExe = $p
    break
}
if (-not $pythonExe) {
    Fail "No usable Python found. Install Python 3.9+ from https://www.python.org/downloads/ (the Microsoft Store stub does not count), then re-run."
}

& $pythonExe -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
if ($LASTEXITCODE -ne 0) {
    $ver = (& $pythonExe -V 2>&1) | Out-String
    Fail "Python 3.9 or newer is required (found: $($ver.Trim()) at $pythonExe)."
}

# Prefer pythonw.exe (no console window) next to python.exe.
$runExe = $pythonExe
$pythonw = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonw) { $runExe = $pythonw }

New-Item -ItemType Directory -Force -Path (Join-Path $scriptDir 'backups') | Out-Null

Write-Host "Registering scheduled task '$taskName'..." -ForegroundColor Cyan
Write-Host "  Interpreter: $runExe"
Write-Host "  Script:      $daemon"

$action   = New-ScheduledTaskAction -Execute $runExe -Argument "`"$daemon`"" -WorkingDirectory $scriptDir
$user     = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -Hidden -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
} catch {
    Fail "Could not register or start the task: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "ProjectVault_Daemon registered and started. It will run hidden at every logon." -ForegroundColor Green
Write-Host "Check status : Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo"
Write-Host "Log file     : $(Join-Path $scriptDir 'backups\vault_daemon.log')"
Write-Host "Uninstall    : run uninstall_service_windows.bat"
