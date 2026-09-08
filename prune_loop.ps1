# Keep the failed-episode images from filling the disk during the long collection.
# A failed episode runs the full 600 steps and costs ~184 MB, of which 183 MB is images that
# nothing downstream reads: the recovery experiment uses only snap_*.npz + meta.json, and the
# start-frame success analysis uses only top/0000.jpg. 41_prune_fails.py keeps exactly those.
# Runs every 30 minutes while collection is alive.
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$log = "$base\prune_loop.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $log; Write-Host $m }
Mark "prune loop armed (every 30min while collecting)"
while ($true) {
    $busy = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '(balance_worker|run_collect3|16_collect_distill)' -and $_.CommandLine -notmatch 'Win32_Process' }).Count
    $free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
    $out = & $venv "$base\41_prune_fails.py" 2>&1 | Select-Object -Last 1
    Mark "free ${free}GB | $out"
    if ($busy -eq 0) { Mark "collection finished - prune loop exits"; break }
    Start-Sleep -Seconds 1800
}
