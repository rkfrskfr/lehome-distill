# Disk guard for the unattended four-type collection (about 40 hours, ~100 GB of raw episodes).
# If free space on C: falls below the threshold, stop collecting rather than filling the disk —
# a full disk would corrupt the episode being written and break every other job on the machine.
# Collection is resumable (run_collect3.ps1 skips garments that already have enough), so stopping
# early costs nothing but time.
# ASCII only.
param([int]$MinFreeGB = 40, [int]$EveryMin = 10)
$base = "C:\Users\H\Desktop\lehome-win"
$mark = "$base\disk_guard.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
Mark "disk guard armed (stop below ${MinFreeGB}GB, check every ${EveryMin}min)"
while ($true) {
    $free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
    $busy = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '(balance_worker|run_collect3|16_collect_distill)' -and $_.CommandLine -notmatch 'Win32_Process' }).Count
    if ($busy -eq 0) { Mark "collection finished (free ${free}GB) - guard exits"; break }
    if ($free -lt $MinFreeGB) {
        Mark "!! free ${free}GB below ${MinFreeGB}GB - stopping collection"
        Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '(balance2|balance_worker|run_collect3|16_collect_distill)' -and $_.CommandLine -notmatch 'Win32_Process' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Mark "collection stopped. Free space, then rerun balance2.ps1 - it resumes where it left off."
        break
    }
    Start-Sleep -Seconds ($EveryMin * 60)
}
