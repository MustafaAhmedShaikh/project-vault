# Removes the ProjectVault_Daemon Scheduled Task. Safe to run more than once.
# Does not touch your project files or backups.
$taskName = 'ProjectVault_Daemon'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed scheduled task '$taskName'." -ForegroundColor Green
} else {
    Write-Host "Task '$taskName' not found (already uninstalled)."
}
Write-Host "Your files and backups were not touched."
Write-Host "If the daemon is still running, end 'pythonw.exe' in Task Manager or sign out."
