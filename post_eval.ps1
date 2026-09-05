# Serialized evaluations under the corrected judge (v3). Runs AFTER the teacher re-eval
# and the Seen_8 collection, and never alongside another 14_benchmark process
# (GPU VRAM oversubscription made every job 10x slower on 09-05 evening).
#   1) champion replicate  final_n5_rep   (act_student_r3plus_aug/060000, seeds 201..212)
#   2) augmentation-off    noaug_full_n5  (act_student_r3plus/060000,     seeds 1..12)
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$py = "C:\isaacsim\python.bat"
$port = 8768
$mark = "$base\post_eval_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function OtherBenchRunning {
    $ps = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'kit.exe' -and $_.CommandLine -match '(14_benchmark|16_collect_distill|22_replay_snapshots)' }
    return ($ps | Measure-Object).Count -gt 0
}
function WaitQuiet([string]$why) {
    # wait until no other Isaac eval/collect process is running (max 8 h)
    $t = 0
    while ((OtherBenchRunning) -and $t -lt 480) { if ($t % 30 -eq 0) { Mark "waiting for GPU ($why)" }; Start-Sleep -Seconds 60; $t++ }
}
function MarkerDone([string]$file, [string]$pat) {
    return (Test-Path $file) -and (Select-String -Path $file -Pattern $pat -Quiet)
}
function Stop-Srv {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' -and $_.CommandLine -match "--port $port" -and $_.CommandLine -notmatch 'Win32_Process' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $t = 0; while ((PortUp $port) -and $t -lt 30) { Start-Sleep -Seconds 2; $t++ }
}
function Start-Srv([string]$ckpt, [string]$tag) {
    Stop-Srv
    Start-Process -WindowStyle Hidden -FilePath $venv `
        -ArgumentList "$base\12_policy_server.py", $ckpt, "--n-action-steps", "5", "--port", "$port" `
        -RedirectStandardOutput "$base\server_$tag.log" -RedirectStandardError "$base\server_$tag.err.log" -WorkingDirectory $base
    $t = 0; while (-not (PortUp $port) -and $t -lt 60) { Start-Sleep -Seconds 3; $t++ }
    return (PortUp $port)
}
function Eval-All([string]$ckpt, [string]$tag, [int]$seedBase) {
    if (Test-Path "$base\bench_$tag.csv") { Remove-Item "$base\bench_$tag.csv" -Force }
    $all = Get-ChildItem "$base\Assets\objects\Challenge_Garment\Release\Top_Long" -Directory |
        Where-Object { $_.Name -match "_(Seen|Unseen)_\d+$" } | Sort-Object Name
    $i = 0
    foreach ($gd in $all) {
        $i++
        WaitQuiet "$tag $($gd.Name)"
        if (-not (PortUp $port)) { if (-not (Start-Srv $ckpt $tag)) { Mark "server failed $tag"; return } }
        & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes 10 --steps 600 `
            --port $port --tag $tag --seed ($seedBase + $i) --reset-mode initial --phys-per-action 2
    }
    $rows = @{}
    if (Test-Path "$base\bench_$tag.csv") { Import-Csv "$base\bench_$tag.csv" | ForEach-Object { $rows[$_.garment] = [int]$rows[$_.garment] + 1 } }
    $i = 0
    foreach ($gd in $all) {
        $i++
        $need = 10 - [int]$rows[$gd.Name]
        if ($need -gt 0) {
            WaitQuiet "$tag topup $($gd.Name)"
            if (-not (PortUp $port)) { Start-Srv $ckpt $tag | Out-Null }
            & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes $need --steps 600 `
                --port $port --tag $tag --seed ($seedBase + 50 + $i) --reset-mode initial --phys-per-action 2
        }
    }
    Stop-Srv
}

Mark "post_eval armed - waiting for TEACHER-EVAL-DONE and SEEN8-DONE"
$t = 0
while ($t -lt (20 * 60)) {
    $a = MarkerDone "$base\teacher_eval_markers.log" 'TEACHER-EVAL-DONE'
    $b = MarkerDone "$base\seen8_markers.log" '(SEEN8-DONE|abort)'
    if ($a -and $b) { break }
    Start-Sleep -Seconds 60; $t++
}
Mark "1 champion replicate (seeds 201..212)"
Eval-All "$base\outputs\act_student_r3plus_aug\checkpoints\060000\pretrained_model" "final_n5_rep" 200
Mark "2 noaug ablation (seeds 1..12)"
Eval-All "$base\outputs\act_student_r3plus\checkpoints\060000\pretrained_model" "noaug_full_n5" 0
Mark "POST-EVAL-DONE"
