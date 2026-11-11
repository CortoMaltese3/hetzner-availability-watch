# Start the watch workflow every few minutes while this PC is on, and alert here when it finds something.
# GitHub's own */5 schedule fires only every few hours; a manual dispatch starts at once.
# Needs `gh` logged in with the `workflow` scope. One loop per PC (a named mutex).
# Start: powershell -NoProfile -File dispatch-loop.ps1   (add -WindowStyle Minimized to hide the window)
# Alert: ~45 s after each dispatch it looks for an open `available` issue. While one is open it prints a
# highlighted line every cycle; a new issue also beeps and raises a Windows toast. No agent is involved.
param(
    [int]$Minutes = 5,
    [string]$Repo = 'CortoMaltese3/hetzner-availability-watch'
)

$settleSeconds = 45   # the watch run takes ~10 s; wait for it before reading the issue list

function Show-Toast([string]$title, [string]$text) {
    try {
        [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
        [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml('<toast scenario="reminder"><visual><binding template="ToastGeneric"><text/><text/></binding></visual></toast>')
        $nodes = $xml.GetElementsByTagName('text')
        [void]$nodes.Item(0).AppendChild($xml.CreateTextNode($title))
        [void]$nodes.Item(1).AppendChild($xml.CreateTextNode($text))
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
    } catch {
        Write-Host "toast failed: $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

function Test-Available([string]$at) {
    $json = gh issue list -R $Repo --label available --state open --json number,title,url --limit 5 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$at UTC alert check failed (gh exit $LASTEXITCODE)" -ForegroundColor Yellow
        return
    }
    # PowerShell 5.1 turns '[]' into one empty element, so keep only entries that have a number.
    $open = @(($json -join "`n") | ConvertFrom-Json | Where-Object { $_.number })
    if ($open.Count -eq 0) {
        $script:alerted = @()
        return
    }
    foreach ($issue in $open) {
        Write-Host "$at UTC AVAILABLE: $($issue.title)  $($issue.url)" -ForegroundColor Black -BackgroundColor Yellow
        if ($script:alerted -notcontains $issue.number) {
            $script:alerted += $issue.number
            foreach ($i in 1..3) { [Console]::Beep(1000, 300) }
            Show-Toast 'Hetzner server available' $issue.title
        }
    }
}

$mutex = New-Object System.Threading.Mutex($false, 'Local\hetzner-watch-dispatch')
if (-not $mutex.WaitOne(0)) {
    Write-Host 'Another dispatch loop is already running on this PC.'
    exit 0
}

$script:alerted = @()
$Host.UI.RawUI.WindowTitle = "hetzner watch: dispatch every $Minutes min"
while ($true) {
    $at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')
    gh workflow run watch.yml -R $Repo --ref main *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "$at UTC dispatched"
    } else {
        Write-Host "$at UTC dispatch failed (gh exit $LASTEXITCODE)"
    }
    Start-Sleep -Seconds $settleSeconds
    Test-Available ((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm'))
    Start-Sleep -Seconds ([Math]::Max(1, $Minutes * 60 - $settleSeconds))
}
