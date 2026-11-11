# Start the watch workflow every few minutes while this PC is on.
# GitHub's own */5 schedule fires only every few hours; a manual dispatch starts at once.
# Needs `gh` logged in with the `workflow` scope. One loop per PC (a named mutex).
# Start: powershell -NoProfile -WindowStyle Minimized -File dispatch-loop.ps1
param(
    [int]$Minutes = 5,
    [string]$Repo = 'CortoMaltese3/hetzner-availability-watch'
)

$mutex = New-Object System.Threading.Mutex($false, 'Local\hetzner-watch-dispatch')
if (-not $mutex.WaitOne(0)) {
    Write-Host 'Another dispatch loop is already running on this PC.'
    exit 0
}

$Host.UI.RawUI.WindowTitle = "hetzner watch: dispatch every $Minutes min"
while ($true) {
    $at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')
    gh workflow run watch.yml -R $Repo --ref main *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "$at UTC dispatched"
    } else {
        Write-Host "$at UTC dispatch failed (gh exit $LASTEXITCODE)"
    }
    Start-Sleep -Seconds ($Minutes * 60)
}
