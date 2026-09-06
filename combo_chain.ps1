# Combined-data student (2026-09-06 17:00): old randomized demonstrations (distill_data_cur = rand+r3+r4,
# 505 eps, collected from the buggy 34 cm drop) + new corrected-environment demonstrations
# (distill_data_fix, 169 eps). Motivation: under the corrected environment the 505-ep model (cur_n5)
# reached ~79% on the first 9 garments vs 58% for the 267-ep champion -> data scale matters; add the
# in-distribution new data on top.
#   1) build distill_data_combo (junctions) -> convert -> train act_student_combo (60k, batch16, aug)
#   2) eval combo_n5 on port 8769 (own server port; GPU-quiet gate)
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$train = "C:\Users\H\Desktop\lerobot\.venv\Scripts\lerobot-train.exe"
$py = "C:\isaacsim\python.bat"
$port = 8769
$mark = "$base\combo_chain_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function TrainingRunning {
    $ps = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'lerobot-train' -and $_.CommandLine -notmatch 'Win32_Process' }
    return ($ps | Measure-Object).Count -gt 0
}
function IsaacCount {
    $ps = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'kit.exe' -and $_.CommandLine -match '(14_benchmark|16_collect_distill|22_replay_snapshots|32_judge_probe|35_frame_probe)' }
    return ($ps | Measure-Object).Count
}
function WaitQuiet([string]$why) {
    $t = 0; $okStreak = 0
    while ($t -lt 900) {
        $n = IsaacCount
        $quiet = ($n -eq 0) -or ($n -le 1 -and -not (TrainingRunning))
        if ($quiet) { $okStreak++; if ($okStreak -ge 2) { break }; Start-Sleep -Seconds 45; continue }
        $okStreak = 0
        if ($t % 30 -eq 0) { Mark "waiting for GPU ($why; isaac=$n training=$(TrainingRunning))" }
        Start-Sleep -Seconds 60; $t++
    }
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
    foreach ($k in @("LEHOME_RAND_LIGHT","LEHOME_RAND_TABLE_TEX","LEHOME_RAND_GARMENT_TEX","LEHOME_RAND_CAM","LEHOME_RAND_PERSTEP","LEHOME_DROP_Z_RANGE","LEHOME_ROBOT_Z")) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
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

# ---- 1) build the combined episode directory (junctions; no copies)
Mark "1 build distill_data_combo"
$dst = "$base\distill_data_combo"
Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force $dst | Out-Null
$n = 0
foreach ($d in Get-ChildItem "$base\distill_data_cur" -Directory) {
    if (Test-Path (Join-Path $d.FullName 'meta.json')) { New-Item -ItemType Junction -Path (Join-Path $dst "old__$($d.Name)") -Target $d.FullName | Out-Null; $n++ }
}
foreach ($d in Get-ChildItem "$base\distill_data_fix" -Directory) {
    if (Test-Path (Join-Path $d.FullName 'meta.json')) { New-Item -ItemType Junction -Path (Join-Path $dst "fix__$($d.Name)") -Target $d.FullName | Out-Null; $n++ }
}
Mark "combo episodes: $n"
if ($n -lt 400) { Mark "too few episodes - abort"; exit 1 }

# ---- 2) convert + train
Mark "2 convert"
& $venv "$base\17_convert_distill.py" --src distill_data_combo --dst distill_lerobot_combo --repo-id hd/lehome_combo *>> "$base\convert_combo.log"
Mark "2 train act_student_combo"
$a = @("--dataset.repo_id=hd/lehome_combo", "--dataset.root=$base\distill_lerobot_combo", "--policy.type=act", "--output_dir=$base\outputs\act_student_combo",
    "--steps=60000", "--batch_size=16", "--num_workers=4", "--seed=1000", "--save_freq=20000",
    "--wandb.enable=false", "--policy.push_to_hub=false",
    "--dataset.image_transforms.enable=true", "--dataset.image_transforms.max_num_transforms=3")
& $train $a *>> "$base\train_act_student_combo.log"
$ck = "$base\outputs\act_student_combo\checkpoints\060000\pretrained_model"
if (-not (Test-Path $ck)) { Mark "TRAIN FAILED"; exit 1 }

# ---- 3) eval
Mark "3 eval combo_n5"
Eval-All $ck "combo_n5" 600
Mark "COMBO-DONE"
