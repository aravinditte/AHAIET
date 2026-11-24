# Register the AHAIET retention sweep as a Windows Scheduled Task
# (AHAIET-016). The sweep itself is backend/app/maintenance.py; this
# script only schedules it — daily at 03:30 by default — and the task
# can be removed with Unregister-ScheduledTask -TaskName "AHAIET Retention Sweep".
# Linux equivalent: a systemd timer or a cron line running
#   cd /path/to/ahaiet/backend && .venv/bin/python -m app.maintenance
# once a day (see docs/SECURITY.md, retention section).
param([string]$Time = "03:30")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Backend venv not found at $python - run scripts\setup-windows.ps1 first." }
$action = New-ScheduledTaskAction -Execute $python -Argument "-m app.maintenance" -WorkingDirectory (Join-Path $Root "backend")
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
Register-ScheduledTask -TaskName "AHAIET Retention Sweep" -Action $action -Trigger $trigger `
    -Description "AHAIET retention sweep: deletes uploads/jobs/cache older than AHAIET_RETENTION_DAYS and records the run in maintenance_runs." -Force
Write-Host "Registered 'AHAIET Retention Sweep' (daily at $Time). Last-sweep status is exposed at GET /api/capabilities -> retention.last_sweep."
