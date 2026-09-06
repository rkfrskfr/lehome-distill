# Extra evaluations on port 8768 while the GPU has headroom (training + 1 Isaac). ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$py = "C:\isaacsim\python.bat"
$port = 8768
$mark = "$base\extra_eval3_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function OtherBenchRunning {
    $ps = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'kit.exe' -and $_.CommandLine -match '(14_benchmark|16_collect_distill|22_replay_snapshots|32_judge_probe|35_frame_probe)' -and $_.CommandLine -notmatch "--port $port" }
    return ($ps | Measure-Object).Count -gt 0
}
function TrainingRunning {
    $ps = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'lerobot-train' -and $_.CommandLine -notmatch 'Win32_Process' }
    return ($ps | Measure-Object).Count -gt 0
}
function IsaacCount {
    $ps = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'kit.exe' -and $_.CommandLine -match '(14_benchmark|16_collect_distill|22_replay_snapshots|32_judge_probe|35_frame_probe)' }
    return ($ps | Measure-Object).Count
}
function WaitQuiet([string]$why) {
    # VRAM budget (32 GB, JAX teacher ~9 GB resident): training + 1 Isaac, or 2 Isaac without training.
    $t = 0; $okStreak = 0
    while ($t -lt 900) {
        $n = IsaacCount
        $quiet = ($n -eq 0) -or ($n -le 1 -and -not (TrainingRunning))
        if ($quiet) {
            # debounce: the condition must hold twice, 45 s apart (a process may be spawning)
            $okStreak++; if ($okStreak -ge 2) { break }; Start-Sleep -Seconds 45; continue
        }
        $okStreak = 0
        if ($t % 30 -eq 0) { Mark "waiting for GPU ($why; isaac=$n training=$(TrainingRunning))" }
        Start-Sleep -Seconds 60; $t++
    }
}
function MarkerDone([string]$file, [string]$pat) { return (Test-Path $file) -and (Select-String -Path $file -Pattern $pat -Quiet) }
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
    if (-not (Test-Path $ckpt)) { Mark "checkpoint missing for $tag - skip"; return }
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

# Start only after the corrected-environment collection is finished (COLLECT-FIX-DONE, or fix_chain gone):
# a kit.exe-count gate alone raced with the collection process spawning (09-06 01:07) and oversubscribed the GPU.
# Second 120-episode pass of the combined-data model (disjoint seeds) -> n=240 for the headline.
Mark "extra_eval3: combo 060000 second pass (seeds 801..812)"
Eval-All "$base\outputs\act_student_combo\checkpoints\060000\pretrained_model" "combo_n5b" 800
Mark "EXTRA-EVAL3-DONE"
