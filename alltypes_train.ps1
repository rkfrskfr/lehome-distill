# Four-garment-type model (2026-09-08). Once all four types are collected, build one dataset,
# train a single student on all of them, and evaluate on all four — that average is the number
# the competition ranks by (the winner scored 79.63% overall).
#
# Recipe: chunk_size=30 (measured 83.3% vs 77.1% for chunk 100 on Top_Long, 09-08) + the proven
# batch 16 / 60k / augmentation-on preset.
# ASCII only.
$base = "C:\Users\H\Desktop\lehome-win"
$venv = "C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
$train = "C:\Users\H\Desktop\lerobot\.venv\Scripts\lerobot-train.exe"
$port = 8794
$mark = "$base\alltypes_train_markers.log"
function Mark([string]$m) { "$(Get-Date -Format 'MM-dd HH:mm')  $m" | Out-File -Append -Encoding ascii $mark; Write-Host $m }
function PortUp([int]$p) { return (Test-NetConnection -ComputerName 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue) }
function MarkerDone([string]$f, [string]$p) { return (Test-Path $f) -and (Select-String -Path $f -Pattern $p -Quiet) }

# ---- 1) wait for the four-type collection to finish
Mark "alltypes_train armed - waiting for ALLTYPES-COLLECT-DONE"
$t = 0
while ($t -lt 900) {
    if (MarkerDone "$base\alltypes_markers.log" 'ALLTYPES-COLLECT-DONE') { break }
    $alive = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'alltypes_chain\.ps1' -and $_.CommandLine -notmatch 'Win32_Process' }
    if (-not $alive) { Mark "alltypes_chain gone - proceeding"; break }
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
& $venv "$base\17_convert_distill.py" --src distill_data_all4 --dst distill_lerobot_all4 --repo-id hd/lehome_all4 *>> "$base\convert_all4.log"
Mark "train act_student_all4 (chunk 30)"
$a = @("--dataset.repo_id=hd/lehome_all4", "--dataset.root=$base\distill_lerobot_all4",
    "--policy.type=act", "--output_dir=$base\outputs\act_student_all4",
    "--steps=60000", "--batch_size=16", "--num_workers=4", "--seed=1000", "--save_freq=20000",
    "--wandb.enable=false", "--policy.push_to_hub=false",
    "--dataset.image_transforms.enable=true", "--dataset.image_transforms.max_num_transforms=3",
    "--policy.chunk_size=30", "--policy.n_action_steps=5")
& $train $a *>> "$base\train_act_student_all4.log"
$ck = "$base\outputs\act_student_all4\checkpoints\060000\pretrained_model"
if (-not (Test-Path $ck)) { Mark "TRAIN FAILED"; exit 1 }

# ---- 4) evaluate all four types = the competition-comparable number
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' -and $_.CommandLine -match "--port $port" -and $_.CommandLine -notmatch 'Win32_Process' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -WindowStyle Hidden -FilePath $venv `
    -ArgumentList "$base\12_policy_server.py", $ck, "--n-action-steps", "5", "--port", "$port" `
    -RedirectStandardOutput "$base\server_all4.log" -RedirectStandardError "$base\server_all4.err.log" -WorkingDirectory $base
$t = 0; while (-not (PortUp $port) -and $t -lt 60) { Start-Sleep -Seconds 3; $t++ }
if (-not (PortUp $port)) { Mark "server failed"; exit 1 }
Mark "eval all4_n5 (4 types x 12 garments x 10)"
& powershell -ExecutionPolicy Bypass -File "$base\run_full_bench4.ps1" -Tag "all4_n5" -Port $port -Episodes 10 -SeedBase 1600
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '12_policy_server' -and $_.CommandLine -match "--port $port" -and $_.CommandLine -notmatch 'Win32_Process' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Mark "ALLTYPES-TRAIN-DONE"
