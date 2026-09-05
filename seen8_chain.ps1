# Seen_8 data collection (first ever: the garment was unpassable under the old judge).
# Waits for the teacher re-evaluation to finish (relay 8767 serves one client at a time),
# then collects with the cycle-3 recipe (snapshots + keep-fail, widened randomization).
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$mark = "$base\seen8_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function TeacherEvalRunning {
    $ps = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'teacher_eval\.ps1' -and $_.CommandLine -notmatch 'Win32_Process' }
    return ($ps | Measure-Object).Count -gt 0
}

Mark "seen8 chain armed - waiting for TEACHER-EVAL-DONE"
$t = 0
while ($t -lt (12 * 60)) {   # up to 12 h
    $done = (Test-Path "$base\teacher_eval_markers.log") -and (Select-String -Path "$base\teacher_eval_markers.log" -Pattern 'TEACHER-EVAL-DONE' -Quiet)
    if ($done -or -not (TeacherEvalRunning)) { break }
    Start-Sleep -Seconds 60; $t++
}
if (-not (PortUp 8767)) { Mark "relay 8767 down - abort"; exit 1 }
Mark "collect Seen_8 start (24 keeps, 2 chunks, seeds 3000+)"
& powershell -ExecutionPolicy Bypass -File "$base\run_collect3.ps1" -Only '_Seen_8$' -Keeps 24 -Chunks 2 -Out distill_data_r4 -SeedBase 3000 -GarmentTex half
$n = @(Get-ChildItem "$base\distill_data_r4" -Directory -Filter "Top_Long_Seen_8_*" -ErrorAction SilentlyContinue).Count
$nf = @(Get-ChildItem "$base\distill_data_r4_fail" -Directory -Filter "Top_Long_Seen_8_*" -ErrorAction SilentlyContinue).Count
Mark "SEEN8-DONE keeps=$n fails=$nf"
