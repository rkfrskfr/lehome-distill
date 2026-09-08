# Four-garment-type model (2026-09-08). Once all four types are collected, build one dataset,
# train a single student on all of them, and evaluate on all four — that average is the number
# the competition ranks by (the winner scored 79.63% overall).
#
# Recipe: chunk_size=30 (measured 83.3% vs 77.1% for chunk 100 on Top_Long, 09-08) plus the proven
# batch 16 / augmentation-on preset, but 120k steps instead of 60k.
# Why 120k: the four-type set is ~230k frames against 112k for the current best, so 60k steps at
# batch 16 would be 4.2 passes over the data instead of 8.5. More passes still help at this scale —
# the 505-episode model scored 70.0% at 40k steps and 75.8% at 60k. Checkpoints every 20k let us
# evaluate 60k against 120k and see whether it saturates.
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$train = "C:\Users\H\Desktop\lerobot\.venv\Scripts\lerobot-train.exe"
$port = 8794
$mark = "$base\alltypes_train_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function MarkerDone([string]$f, [string]$p) { return (Test-Path $f) -and (Select-String -Path $f -Pattern $p -Quiet) }
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

# ---- 1) wait for the BALANCING pass, not just the first collection.
# The first pass left Top_Long with 914 episodes and the three new types with about 150 each (6:1),
# which would make a "four-type average" mostly a Top_Long score. balance_chain.ps1 tops the three
# new types up to about 480 episodes each before we train.
Mark "alltypes_train armed - waiting for BALANCE-DONE"
$t = 0
while ($t -lt 3000) {
    if (MarkerDone "$base\balance_markers.log" 'BALANCE-DONE') { break }
    $alive = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'balance_chain\.ps1' -and $_.CommandLine -notmatch 'Win32_Process' }
    if (-not $alive) { Mark "balance_chain gone - proceeding with whatever is on disk"; break }
    Start-Sleep -Seconds 60; $t++
}

# ---- 2) one folder of junctions over every episode we have, all four types
Mark "build distill_data_all4"
$dst = "$base\distill_data_all4"
Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $dst | Out-Null
$n = 0
foreach ($src in 'distill_data_rand','distill_data_r3','distill_data_r4','distill_data_fix',
                 'distill_data_fix2','distill_data_top_short','distill_data_pant_long',
                 'distill_data_pant_short') {
    $c = 0
    foreach ($d in Get-ChildItem "$base\$src" -Directory -ErrorAction SilentlyContinue) {
        if (Test-Path (Join-Path $d.FullName 'meta.json')) {
            New-Item -ItemType Junction -Path (Join-Path $dst "$($src)__$($d.Name)") -Target $d.FullName | Out-Null
            $c++; $n++
        }
    }
    Mark "  $src : $c"
}
Mark "total $n episodes"
if ($n -lt 800) { Mark "too few episodes ($n) - abort"; exit 1 }

# ---- 3) convert and train
Mark "convert -> distill_lerobot_all4"
Remove-Item "$base\distill_lerobot_all4" -Recurse -Force -ErrorAction SilentlyContinue
& $venv "$base\17_convert_distill.py" --src distill_data_all4 --dst distill_lerobot_all4 --repo-id hd/lehome_all4 *>> "$base\convert_all4.log"
Mark "train act_student_all4 (chunk 30, 120k steps = about 8.3 passes)"
$a = @("--dataset.repo_id=hd/lehome_all4", "--dataset.root=$base\distill_lerobot_all4",
    "--policy.type=act", "--output_dir=$base\outputs\act_student_all4",
    "--steps=120000", "--batch_size=16", "--num_workers=4", "--seed=1000", "--save_freq=20000",
    "--wandb.enable=false", "--policy.push_to_hub=false",
    "--dataset.image_transforms.enable=true", "--dataset.image_transforms.max_num_transforms=3",
    "--policy.chunk_size=30", "--policy.n_action_steps=5")
& $train $a *>> "$base\train_act_student_all4.log"

$ck120 = Join-Path $base "outputs\act_student_all4\checkpoints\120000\pretrained_model"
$ck60 = Join-Path $base "outputs\act_student_all4\checkpoints\060000\pretrained_model"
if (-not (Test-Path $ck120)) { Mark "TRAIN FAILED (no 120k checkpoint)"; exit 1 }

# ---- 4) the competition-comparable number: all four types
if (Start-Srv $ck120 "all4") {
    Mark "eval all4_n5 (120k, 4 types x 12 garments x 10)"
    & powershell -ExecutionPolicy Bypass -File "$base\run_full_bench4.ps1" -Tag "all4_n5" -Port $port -Episodes 10 -SeedBase 1600
    Stop-Srv
} else { Mark "server failed for 120k" }

# ---- 5) same data, same settings, half the training — answers "does longer training pay off"
if (Test-Path $ck60) {
    if (Start-Srv $ck60 "all4_60k") {
        Mark "eval all4_60k_n5 (60k, step-count comparison)"
        & powershell -ExecutionPolicy Bypass -File "$base\run_full_bench4.ps1" -Tag "all4_60k_n5" -Port $port -Episodes 10 -SeedBase 1800
        Stop-Srv
    } else { Mark "server failed for 60k" }
}
Mark "ALLTYPES-TRAIN-DONE"
