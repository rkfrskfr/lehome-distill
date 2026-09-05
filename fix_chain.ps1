# Corrected-environment pipeline (2026-09-05 night). After the judge (17:00) and initial-pose (20:35)
# fixes, every earlier demonstration was collected from a 34 cm drop; re-collect on the fixed
# environment and train a fresh student.
#   1) wait TEACHER-EVAL-DONE (relay 8767 is single-client)
#   2) collect all 10 Seen garments incl. Seen_8 -> distill_data_fix  (16 keeps x garment, 2 chunks)
#   3) convert -> distill_lerobot_fix, train act_student_fix (proven recipe: 60k, batch16, aug)
#   4) eval fix_n5 on port 8766 when no other Isaac process runs
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$train = "C:\Users\H\Desktop\lerobot\.venv\Scripts\lerobot-train.exe"
$py = "C:\isaacsim\python.bat"
$mark = "$base\fix_chain_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function MarkerDone([string]$file, [string]$pat) { return (Test-Path $file) -and (Select-String -Path $file -Pattern $pat -Quiet) }
function OtherIsaacRunning {
    $ps = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'kit.exe' -and $_.CommandLine -match '(14_benchmark|16_collect_distill|22_replay_snapshots|32_judge_probe|35_frame_probe)' }
    return ($ps | Measure-Object).Count -gt 0
}
function WaitQuiet([string]$why) {
    $t = 0
    while ((OtherIsaacRunning) -and $t -lt 900) { if ($t % 30 -eq 0) { Mark "waiting for GPU ($why)" }; Start-Sleep -Seconds 60; $t++ }
}
function Stop-Student {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' -and $_.CommandLine -notmatch '--port' -and $_.CommandLine -notmatch 'Win32_Process' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $t = 0; while ((PortUp 8766) -and $t -lt 30) { Start-Sleep -Seconds 2; $t++ }
}
function Start-Student([string]$ckpt, [string]$tag) {
    Stop-Student
    Start-Process -WindowStyle Hidden -FilePath $venv `
        -ArgumentList "$base\12_policy_server.py", $ckpt, "--n-action-steps", "5" `
        -RedirectStandardOutput "$base\server_$tag.log" -RedirectStandardError "$base\server_$tag.err.log" -WorkingDirectory $base
    $t = 0; while (-not (PortUp 8766) -and $t -lt 60) { Start-Sleep -Seconds 3; $t++ }
    return (PortUp 8766)
}
function Full-Eval([string]$ckpt, [string]$tag, [int]$seedBase) {
    foreach ($k in @("LEHOME_RAND_LIGHT","LEHOME_RAND_TABLE_TEX","LEHOME_RAND_GARMENT_TEX","LEHOME_RAND_CAM","LEHOME_RAND_PERSTEP","LEHOME_DROP_Z_RANGE","LEHOME_ROBOT_Z")) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    if (Test-Path "$base\bench_$tag.csv") { Remove-Item "$base\bench_$tag.csv" -Force }
    $all = Get-ChildItem "$base\Assets\objects\Challenge_Garment\Release\Top_Long" -Directory |
        Where-Object { $_.Name -match "_(Seen|Unseen)_\d+$" } | Sort-Object Name
    $i = 0
    foreach ($gd in $all) {
        $i++
        WaitQuiet "$tag $($gd.Name)"
        if (-not (PortUp 8766)) { if (-not (Start-Student $ckpt $tag)) { Mark "server failed for $tag"; return } }
        & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes 10 --steps 600 `
            --port 8766 --tag $tag --seed ($seedBase + $i) --reset-mode initial --phys-per-action 2
    }
    $rows = @{}
    if (Test-Path "$base\bench_$tag.csv") { Import-Csv "$base\bench_$tag.csv" | ForEach-Object { $rows[$_.garment] = [int]$rows[$_.garment] + 1 } }
    $i = 0
    foreach ($gd in $all) {
        $i++
        $need = 10 - [int]$rows[$gd.Name]
        if ($need -gt 0) {
            WaitQuiet "$tag topup $($gd.Name)"
            if (-not (PortUp 8766)) { Start-Student $ckpt $tag | Out-Null }
            & $py "$base\14_benchmark.py" --garment-dir $gd.Name --garment-type Top_Long --episodes $need --steps 600 `
                --port 8766 --tag $tag --seed ($seedBase + 50 + $i) --reset-mode initial --phys-per-action 2
        }
    }
    Stop-Student
}

# ---- 1) wait for the teacher re-eval (relay is single-client)
Mark "fix_chain armed - waiting for TEACHER-EVAL-DONE"
$t = 0
while ($t -lt 600) {
    if (MarkerDone "$base\teacher_eval_markers.log" 'TEACHER-EVAL-DONE') { break }
    $alive = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'teacher_eval\.ps1' -and $_.CommandLine -notmatch 'Win32_Process' }
    if (-not $alive) { Mark "teacher_eval process gone - proceeding"; break }
    Start-Sleep -Seconds 60; $t++
}
if (-not (PortUp 8767)) { Mark "relay 8767 down - abort"; exit 1 }

# ---- 2) collection on the corrected environment (all Seen incl. Seen_8)
Mark "2 collect distill_data_fix (10 garments x 16 keeps, 2 chunks, seeds 4000+)"
& powershell -ExecutionPolicy Bypass -File "$base\run_collect3.ps1" -Keeps 16 -Chunks 2 -Out distill_data_fix -SeedBase 4000 -GarmentTex half
$n = @(Get-ChildItem "$base\distill_data_fix" -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'meta.json') }).Count
Mark "COLLECT-FIX-DONE keeps=$n"
# compatibility marker for chains that wait on the Seen_8 collection
"$(Get-Date -Format 'MM-dd HH:mm')  SEEN8-DONE (via fix_chain, keeps=$n)" | Out-File -Append -Encoding ascii "$base\seen8_markers.log"
if ($n -lt 60) { Mark "too few episodes ($n) - skip training"; exit 1 }

# ---- 3) convert + train
Mark "3 convert"
& $venv "$base\17_convert_distill.py" --src distill_data_fix --dst distill_lerobot_fix --repo-id hd/lehome_fix *>> "$base\convert_fix.log"
Mark "3 train act_student_fix"
$a = @("--dataset.repo_id=hd/lehome_fix", "--dataset.root=$base\distill_lerobot_fix", "--policy.type=act", "--output_dir=$base\outputs\act_student_fix",
    "--steps=60000", "--batch_size=16", "--num_workers=4", "--seed=1000", "--save_freq=20000",
    "--wandb.enable=false", "--policy.push_to_hub=false",
    "--dataset.image_transforms.enable=true", "--dataset.image_transforms.max_num_transforms=3")
& $train $a *>> "$base\train_act_student_fix.log"
$ck = "$base\outputs\act_student_fix\checkpoints\060000\pretrained_model"
if (-not (Test-Path $ck)) { Mark "TRAIN FAILED"; exit 1 }

# ---- 4) eval
Mark "4 eval fix_n5"
Full-Eval $ck "fix_n5" 500
Mark "FIX-DONE"
